"""HR business rules: working days, leave balances, approvals, check-in and payroll."""

import calendar
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import notify, users_with_perm

from .models import Attendance, Employee, Holiday, LeaveRequest, LeaveType, NOCRequest, Payslip, ReviewStatus

CENT = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- Calendar ----------

def working_days(start, end):
    """Dates from start to end (inclusive) that are neither weekend days nor holidays."""
    holidays = set(Holiday.objects.filter(date__range=(start, end)).values_list("date", flat=True))
    day, days = start, []
    while day <= end:
        if day.weekday() not in settings.HR_WEEKEND_DAYS and day not in holidays:
            days.append(day)
        day += timedelta(days=1)
    return days


# ---------- Leave ----------

def leave_used(employee, leave_type, year):
    return LeaveRequest.objects.filter(
        employee=employee, leave_type=leave_type, status=ReviewStatus.APPROVED, start_date__year=year
    ).aggregate(total=Sum("days"))["total"] or Decimal("0")


def leave_balances(employee, year=None):
    year = year or timezone.localdate().year
    rows = []
    for lt in LeaveType.objects.all():
        used = leave_used(employee, lt, year)
        rows.append({
            "type": lt,
            "allowed": lt.days_per_year,
            "used": used,
            "remaining": (lt.days_per_year - used) if lt.days_per_year else None,
        })
    return rows


def validate_leave(leave):
    """Return a list of problems with a leave request (empty if it can be submitted)."""
    problems = []
    days = working_days(leave.start_date, leave.end_date)
    if not days:
        problems.append("The selected dates are all weekends or holidays, so no leave is needed.")
    overlapping = LeaveRequest.objects.filter(
        employee=leave.employee,
        status__in=[ReviewStatus.PENDING, ReviewStatus.APPROVED],
        start_date__lte=leave.end_date,
        end_date__gte=leave.start_date,
    ).exclude(pk=leave.pk)
    if overlapping.exists():
        problems.append("These dates overlap another pending or approved leave request.")
    lt = leave.leave_type
    if lt.days_per_year:
        remaining = lt.days_per_year - leave_used(leave.employee, lt, leave.start_date.year)
        if len(days) > remaining:
            problems.append(
                f"Only {remaining:g} day(s) of {lt.name} leave are left this year, but this request needs {len(days)}."
            )
    return problems


@transaction.atomic
def review_leave(leave, *, approve, reviewer, note=""):
    leave.status = ReviewStatus.APPROVED if approve else ReviewStatus.REJECTED
    leave.reviewed_by = reviewer
    leave.reviewed_at = timezone.now()
    if note:
        leave.review_note = note
    leave.save()
    if approve:
        for day in working_days(leave.start_date, leave.end_date):
            Attendance.objects.update_or_create(
                employee=leave.employee, date=day,
                defaults={"status": Attendance.Status.ON_LEAVE, "note": f"{leave.leave_type} leave"},
            )
    notify(
        leave.employee.user,
        f"Leave {'approved' if approve else 'rejected'}: {leave.leave_type}, {leave.start_date:%d %b} – {leave.end_date:%d %b}",
        body=leave.review_note, url=reverse("admin:hr_leaverequest_change", args=[leave.pk]),
        kind=Notification.Kind.SUCCESS if approve else Notification.Kind.WARNING, exclude=reviewer,
    )


def announce_request(obj, what, summary):
    """Tell HR managers a leave or NOC request is waiting."""
    notify(users_with_perm("hr.manage_hr"), f"{what} request from {obj.employee.full_name}", body=summary,
           url=reverse(f"admin:hr_{obj._meta.model_name}_change", args=[obj.pk]),
           kind=Notification.Kind.APPROVAL, exclude=obj.employee.user)


# ---------- NOC ----------

@transaction.atomic
def review_noc(noc, *, approve, reviewer, note=""):
    noc.status = ReviewStatus.APPROVED if approve else ReviewStatus.REJECTED
    noc.reviewed_by = reviewer
    noc.reviewed_at = timezone.now()
    if note:
        noc.review_note = note
    if approve and not noc.reference_no:
        year = timezone.localdate().year
        count = NOCRequest.objects.filter(reference_no__contains=f"/NOC/{year}/").count() + 1
        noc.reference_no = f"{settings.HR_REFERENCE_PREFIX}/NOC/{year}/{count:04d}"
    noc.save()
    notify(
        noc.employee.user,
        f"NOC {'approved' if approve else 'rejected'}: {noc.get_purpose_display()}",
        body="Your letter is ready to print." if approve else noc.review_note,
        url=reverse("admin:hr_nocrequest_changelist"),
        kind=Notification.Kind.SUCCESS if approve else Notification.Kind.WARNING, exclude=reviewer,
    )


# ---------- Attendance ----------

def check_in(employee):
    now = timezone.localtime()
    office_start = datetime.strptime(settings.HR_OFFICE_START, "%H:%M").time()
    late_after = (datetime.combine(now.date(), office_start) + timedelta(minutes=settings.HR_LATE_GRACE_MINUTES)).time()
    record, created = Attendance.objects.get_or_create(
        employee=employee, date=now.date(),
        defaults={
            "check_in": now.time().replace(microsecond=0),
            "status": Attendance.Status.LATE if now.time() > late_after else Attendance.Status.PRESENT,
        },
    )
    return record, created


def check_out(employee):
    now = timezone.localtime()
    record = Attendance.objects.filter(employee=employee, date=now.date()).first()
    if record is None or record.check_in is None:
        return None
    record.check_out = now.time().replace(microsecond=0)
    record.save(update_fields=["check_out"])
    return record


# ---------- Payroll ----------

def build_payslip(employee, year, month, payslip=None):
    """Fill a (new or existing draft) payslip from the employee's salary and the month's attendance."""
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    workdays = set(working_days(first, last))

    records = Attendance.objects.filter(employee=employee, date__range=(first, last))
    absent = Decimal("0")
    for rec in records:
        if rec.date not in workdays:
            continue
        if rec.status == Attendance.Status.ABSENT:
            absent += 1
        elif rec.status == Attendance.Status.HALF_DAY:
            absent += Decimal("0.5")

    unpaid = Decimal("0")
    for leave in LeaveRequest.objects.filter(
        employee=employee, status=ReviewStatus.APPROVED, leave_type__is_paid=False,
        start_date__lte=last, end_date__gte=first,
    ):
        unpaid += len([d for d in working_days(max(leave.start_date, first), min(leave.end_date, last))])

    p = payslip or Payslip(employee=employee, year=year, month=month)
    p.basic_salary = employee.basic_salary
    p.house_rent = employee.house_rent
    p.medical_allowance = employee.medical_allowance
    p.conveyance_allowance = employee.conveyance_allowance
    p.other_allowance = employee.other_allowance
    p.days_in_month = last.day
    p.working_days = len(workdays)
    p.absent_days = absent
    p.unpaid_leave_days = unpaid

    gross = employee.gross_salary
    per_day = gross / p.working_days if p.working_days else Decimal("0")
    p.absence_deduction = _money(per_day * (absent + unpaid))
    p.provident_fund = _money(employee.basic_salary * employee.provident_fund_rate / 100)
    p.tax = _money(employee.monthly_tax)
    p.recalculate_totals()
    return p


@transaction.atomic
def generate_payslips(year, month, user):
    """Create or refresh draft payslips for every active employee. Finalized payslips are never changed."""
    created = updated = skipped = 0
    for employee in Employee.objects.filter(is_active=True, joining_date__lte=date(year, month, calendar.monthrange(year, month)[1])):
        existing = Payslip.objects.filter(employee=employee, year=year, month=month).first()
        if existing and existing.status == Payslip.Status.FINAL:
            skipped += 1
            continue
        # Refreshing an existing draft keeps any manual "other deduction" HR entered on it.
        slip = build_payslip(employee, year, month, payslip=existing)
        if existing:
            updated += 1
        else:
            created += 1
        slip.generated_by = user
        slip.save()
    return created, updated, skipped
