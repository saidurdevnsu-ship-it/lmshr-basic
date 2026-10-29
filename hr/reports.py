"""HR reports: monthly attendance with working hours, and leave taken in the year, per employee."""

import calendar
from collections import defaultdict
from datetime import date, datetime

from django.utils import timezone

from .models import Attendance, LeaveType
from .services import leave_used, working_days

STATUSES = Attendance.Status


def worked_hours(record):
    """Hours between check-in and check-out, or None if either is missing."""
    if not (record.check_in and record.check_out) or record.check_out <= record.check_in:
        return None
    start = datetime.combine(record.date, record.check_in)
    return round((datetime.combine(record.date, record.check_out) - start).total_seconds() / 3600, 2)


def monthly_report(employees, year, month):
    """One row per employee for the month. Unmarked days count only working days up to today."""
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    workdays = set(working_days(first, min(last, timezone.localdate())))
    by_employee = defaultdict(list)
    for record in Attendance.objects.filter(employee__in=employees, date__range=(first, last)):
        by_employee[record.employee_id].append(record)
    leave_types = list(LeaveType.objects.all())

    rows = []
    for employee in employees:
        records = by_employee[employee.pk]
        counts = {status: 0 for status in STATUSES.values}
        hours = []
        for r in records:
            counts[r.status] += 1
            h = worked_hours(r)
            if h is not None:
                hours.append(h)
        rows.append({
            "employee": employee,
            "present": counts[STATUSES.PRESENT],
            "late": counts[STATUSES.LATE],
            "half_day": counts[STATUSES.HALF_DAY],
            "absent": counts[STATUSES.ABSENT],
            "on_leave": counts[STATUSES.ON_LEAVE],
            "unmarked": len(workdays - {r.date for r in records}),
            "hours": round(sum(hours), 2),
            "avg_hours": round(sum(hours) / len(hours), 2) if hours else None,
            "leave_taken": [leave_used(employee, lt, year) for lt in leave_types],
        })
    return {"first": first, "last": last, "working_days": len(workdays), "leave_types": leave_types, "rows": rows}


def report_csv_rows(report):
    """The report as rows for a CSV file (Excel opens it directly)."""
    header = ["Employee ID", "Name", "Department", "Present", "Late", "Half day", "Absent", "On leave", "Not marked",
              "Hours worked", "Average hours / day"]
    header += [f"{lt.name} leave taken ({report['first'].year})" for lt in report["leave_types"]]
    yield header
    for row in report["rows"]:
        e = row["employee"]
        yield [e.employee_id, e.full_name, str(e.department), row["present"], row["late"], row["half_day"],
               row["absent"], row["on_leave"], row["unmarked"], row["hours"], row["avg_hours"] or "",
               *[f"{days:g}" for days in row["leave_taken"]]]
