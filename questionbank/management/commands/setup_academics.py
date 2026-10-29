from django.core.management.base import BaseCommand

from learning.roles import ensure_roles

ROLES = ["Teacher / Subject Expert", "Head of Department", "Exam Controller", "Read-Only"]


class Command(BaseCommand):
    help = ("Create the Teacher / Subject Expert, Head of Department, Exam Controller and Read-Only roles with their "
            "default permissions. Roles that already exist keep their edits unless you pass --reset. "
            "Safe to run more than once.")

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Also restore the default permissions of roles that already exist.")

    def handle(self, *args, reset=False, **options):
        ensure_roles(ROLES, reset=reset, log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS("Academic roles ready."))
