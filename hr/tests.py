from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from . import services
from .models import Attendance, Department, Designation, Employee, LeaveRequest, LeaveType, ReviewStatus

DHAKA = ZoneInfo("Asia/Dhaka")


class HRTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.hr = User.objects.create_superuser("hr", "hr@example.com", "Pw-12345!")
        user = User.objects.create_user("rahim", "rahim@example.com", "Pw-12345!", is_staff=True)
        self.employee = Employee.objects.create(
            user=user, employee_id="T-001", department=Department.objects.create(name="Academics"),
            designation=Designation.objects.create(name="Teacher"), joining_date=date(2025, 1, 1),
        )
        self.casual = LeaveType.objects.create(name="Casual", days_per_year=5)

    def leave(self, start, end, status=ReviewStatus.PENDING):
        return LeaveRequest.objects.create(employee=self.employee, leave_type=self.casual, start_date=start,
                                           end_date=end, reason="Family", status=status,
                                           days=len(services.working_days(start, end)))


class LeaveBalanceTests(HRTestCase):
    # Weekends are Friday and Saturday; 2026-11-01 is a Sunday.

    def test_approval_rechecks_the_balance(self):
        first = self.leave(date(2026, 11, 1), date(2026, 11, 4))   # Sun–Wed: 4 days
        second = self.leave(date(2026, 11, 8), date(2026, 11, 11))  # 4 days; both fit on their own
        services.review_leave(first, approve=True, reviewer=self.hr)
        with self.assertRaisesMessage(services.LeaveError, "Only 1 day(s) of Casual leave are left in 2026"):
            services.review_leave(second, approve=True, reviewer=self.hr)
        second.refresh_from_db()
        self.assertEqual(second.status, ReviewStatus.PENDING)

    def test_leave_over_new_year_counts_in_each_year(self):
        self.leave(date(2026, 12, 29), date(2027, 1, 3), ReviewStatus.APPROVED)  # Tue 29–Thu 31, Sun 3
        self.assertEqual(services.leave_used(self.employee, self.casual, 2026), 3)
        self.assertEqual(services.leave_used(self.employee, self.casual, 2027), 1)

    def test_cancelling_approved_leave_clears_attendance_and_restores_balance(self):
        leave = self.leave(date(2026, 11, 1), date(2026, 11, 2))
        services.review_leave(leave, approve=True, reviewer=self.hr)
        self.assertEqual(Attendance.objects.filter(status=Attendance.Status.ON_LEAVE).count(), 2)
        services.cancel_leave(leave, by=self.hr)
        self.assertEqual(Attendance.objects.count(), 0)
        self.assertEqual(services.leave_used(self.employee, self.casual, 2026), 0)


class CheckInTests(HRTestCase):
    def check_in_at(self, hour, minute):
        now = datetime(2026, 11, 2, hour, minute, tzinfo=DHAKA)
        with mock.patch("hr.services.timezone.localtime", return_value=now):
            return services.check_in(self.employee)

    def test_check_in_after_being_marked_absent(self):
        Attendance.objects.create(employee=self.employee, date=date(2026, 11, 2), status=Attendance.Status.ABSENT)
        record, outcome = self.check_in_at(10, 0)
        self.assertEqual(outcome, "checked_in")
        self.assertEqual(record.status, Attendance.Status.LATE)
        self.assertIsNotNone(record.check_in)

    def test_no_check_in_on_leave(self):
        Attendance.objects.create(employee=self.employee, date=date(2026, 11, 2), status=Attendance.Status.ON_LEAVE)
        record, outcome = self.check_in_at(9, 0)
        self.assertEqual(outcome, "on_leave")
        self.assertIsNone(record.check_in)

    def test_second_check_in(self):
        self.check_in_at(9, 0)
        record, outcome = self.check_in_at(9, 30)
        self.assertEqual(outcome, "already")
        self.assertEqual(record.status, Attendance.Status.PRESENT)
