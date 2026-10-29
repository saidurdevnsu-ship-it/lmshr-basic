from django.core.management.base import BaseCommand

from hr.models import LeaveType
from learning.roles import ensure_roles

DEFAULT_LEAVE_TYPES = [
    ("Casual", 10, True),
    ("Sick", 14, True),
    ("Annual", 20, True),
    ("Unpaid", 0, False),
]


class Command(BaseCommand):
    help = ("Create the default leave types and the HR Manager / Employee roles. Roles that already exist keep their "
            "edits unless you pass --reset. Safe to run more than once.")

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Also restore the default permissions of roles that already exist.")

    def handle(self, *args, reset=False, **options):
        for name, days, paid in DEFAULT_LEAVE_TYPES:
            _, created = LeaveType.objects.get_or_create(name=name, defaults={"days_per_year": days, "is_paid": paid})
            if created:
                self.stdout.write(f"Leave type: {name} ({days or 'no limit'} days, {'paid' if paid else 'unpaid'})")

        ensure_roles(["HR Manager", "Employee"], reset=reset, log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS("HR setup complete."))
