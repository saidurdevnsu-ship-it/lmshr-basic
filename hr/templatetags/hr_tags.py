from datetime import datetime

from django import template
from django.conf import settings
from django.utils import timezone

from hr.admin import is_department_head, is_hr_manager
from hr.models import Attendance, Employee, LeaveRequest, ReviewStatus
from hr.services import leave_balances, working_days

register = template.Library()


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
