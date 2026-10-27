from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from hr.models import LeaveType

DEFAULT_LEAVE_TYPES = [
    ("Casual", 10, True),
    ("Sick", 14, True),
    ("Annual", 20, True),
    ("Unpaid", 0, False),
]

# Employee self-service: their own attendance, leave, NOC and pay slips (the admin limits them to their own records).
EMPLOYEE_PERMISSIONS = [
    "view_employee", "view_attendance", "view_holiday", "view_leavetype",
    "add_leaverequest", "view_leaverequest", "add_nocrequest", "view_nocrequest", "view_payslip",
]


class Command(BaseCommand):
    help = "Create the default leave types and the HR Manager / Employee roles. Safe to run more than once."

    def handle(self, *args, **options):
        for name, days, paid in DEFAULT_LEAVE_TYPES:
            _, created = LeaveType.objects.get_or_create(name=name, defaults={"days_per_year": days, "is_paid": paid})
            if created:
                self.stdout.write(f"Leave type: {name} ({days or 'no limit'} days, {'paid' if paid else 'unpaid'})")

        hr_perms = Permission.objects.filter(content_type__app_label="hr")
        manager, _ = Group.objects.get_or_create(name="HR Manager")
        manager.permissions.add(*hr_perms)
        # View-only on accounts: Django's user form lets anyone with change_user grant superuser status.
        manager.permissions.add(*Permission.objects.filter(content_type__app_label="auth", codename__in=[
            "view_user", "view_group",
        ]))
        self.stdout.write("Role: HR Manager (all HR permissions, can view user accounts)")

        employee, _ = Group.objects.get_or_create(name="Employee")
        employee.permissions.add(*hr_perms.filter(codename__in=EMPLOYEE_PERMISSIONS))
        self.stdout.write("Role: Employee (self-service attendance, leave, NOC, pay slips)")

        self.stdout.write(self.style.SUCCESS("HR setup complete."))
