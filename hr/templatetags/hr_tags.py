from datetime import datetime

from django import template
from django.conf import settings
from django.utils import timezone

from hr.admin import is_department_head, is_hr_manager
from hr.models import Attendance, Employee, LeaveRequest, ReviewStatus
from hr.reports import worked_hours
from hr.services import leave_balances, working_days

register = template.Library()


@register.inclusion_tag("admin/hr/_punch.html", takes_context=True)
def punch_button(context, embedded=False):
    """The round punch in / punch out button for the signed-in user (nothing if they have no employee profile).

    embedded=True drops its own title and card, for use inside a panel that already has them."""
    request = context["request"]
    employee = Employee.objects.filter(user=request.user, is_active=True).first()
    if employee is None:
        return {"employee": None}
    today = timezone.localdate()
    record = Attendance.objects.filter(employee=employee, date=today).first()
    if record and record.status == Attendance.Status.ON_LEAVE and not record.check_in:
        state = "leave"
    elif record and record.check_in and record.check_out:
        state = "done"
    elif record and record.check_in:
        state = "out"
    else:
        state = "in"
    return {
        "employee": employee,
        "record": record,
        "state": state,
        "hours": worked_hours(record) if state == "done" else None,
        "today": today,
        "is_workday": bool(working_days(today, today)),
        "office_start": datetime.strptime(settings.HR_OFFICE_START, "%H:%M").time(),
        "next": request.get_full_path(),
        "embedded": embedded,
        "csrf_token": context.get("csrf_token"),
    }


@register.simple_tag(takes_context=True)
def hr_dashboard(context):
    request = context["request"]
    user = request.user
    today = timezone.localdate()
    data = {
        "today": today,
        "is_workday": bool(working_days(today, today)),
        "is_manager": is_hr_manager(user),
        "office_start": datetime.strptime(settings.HR_OFFICE_START, "%H:%M").time(),
    }

    employee = Employee.objects.filter(user=user).select_related("department", "designation").first()
    data["employee"] = employee
    if employee:
        data["today_record"] = Attendance.objects.filter(employee=employee, date=today).first()
        data["balances"] = leave_balances(employee, today.year)
        data["my_pending"] = LeaveRequest.objects.filter(employee=employee, status=ReviewStatus.PENDING).count()
        data["my_month_attendance"] = list(
            Attendance.objects.filter(employee=employee, date__year=today.year, date__month=today.month)
            .order_by("date")
        )

    if data["is_manager"]:
        active = Employee.objects.filter(is_active=True)
        todays = Attendance.objects.filter(date=today, employee__in=active)
        counts = {s: todays.filter(status=s).count() for s in Attendance.Status.values}
        data["stats"] = {
            "employees": active.count(),
            "present": counts["present"] + counts["late"] + counts["half_day"],
            "late": counts["late"],
            "on_leave": counts["on_leave"],
            "absent": counts["absent"],
            "unmarked": active.count() - todays.count(),
            "pending_leave": LeaveRequest.objects.filter(status=ReviewStatus.PENDING).count(),
        }
        data["pending_leave"] = list(
            LeaveRequest.objects.filter(status=ReviewStatus.PENDING)
            .select_related("employee__user", "leave_type").order_by("start_date")[:6]
        )
    elif is_department_head(user):
        data["is_head"] = True
        data["pending_leave"] = list(
            LeaveRequest.objects.filter(status=ReviewStatus.PENDING, employee__department__head=user)
            .exclude(employee__user=user)
            .select_related("employee__user", "leave_type").order_by("start_date")[:6]
        )
    return data
