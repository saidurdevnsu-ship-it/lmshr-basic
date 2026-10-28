"""HR business rules: working days, leave balances, approvals and check-in."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from notifications.make import leave_approved_data, send_event
from notifications.models import Notification
from notifications.services import notify, users_with_perm

from .models import Attendance, Holiday, LeaveRequest, LeaveType, ReviewStatus


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
        send_event("leave.approved", leave_approved_data(leave))
    notify(
        leave.employee.user,
        f"Leave {'approved' if approve else 'rejected'}: {leave.leave_type}, {leave.start_date:%d %b} – {leave.end_date:%d %b}",
        body=leave.review_note, url=reverse("admin:hr_leaverequest_change", args=[leave.pk]),
        kind=Notification.Kind.SUCCESS if approve else Notification.Kind.WARNING, exclude=reviewer,
    )


def announce_request(obj, what, summary):
    """Tell HR managers a leave request is waiting."""
    notify(users_with_perm("hr.manage_hr"), f"{what} request from {obj.employee.full_name}", body=summary,
           url=reverse(f"admin:hr_{obj._meta.model_name}_change", args=[obj.pk]),
           kind=Notification.Kind.APPROVAL, exclude=obj.employee.user)


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
