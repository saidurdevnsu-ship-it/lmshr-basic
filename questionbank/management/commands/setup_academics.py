from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

FINAL = "manage_final_papers"


def perms(*codenames):
    return list(Permission.objects.filter(content_type__app_label="questionbank", codename__in=codenames))


class Command(BaseCommand):
    help = ("Create the Teacher / Subject Expert, Head of Department and Exam Controller roles for blueprints and "
            "confidential final papers. Safe to run more than once.")

    def handle(self, *args, **options):
        teacher, _ = Group.objects.get_or_create(name="Teacher / Subject Expert")
        teacher.permissions.add(*perms(
            "view_subject", "view_grade", "view_knowledgesource", "view_academicevent",
            "add_question", "change_question", "view_question",
            "add_questionblueprint", "change_questionblueprint", "view_questionblueprint",
            "add_blueprintitem", "change_blueprintitem", "delete_blueprintitem", "view_blueprintitem",
        ))
        self.stdout.write("Role: Teacher / Subject Expert (writes blueprints and sample questions)")

        hod, _ = Group.objects.get_or_create(name="Head of Department")
        hod.permissions.add(*Permission.objects.filter(content_type__app_label="questionbank").exclude(codename=FINAL))
        self.stdout.write("Role: Head of Department (reviews and approves blueprints)")

        controller, _ = Group.objects.get_or_create(name="Exam Controller")
        controller.permissions.add(*perms(
            FINAL, "view_subject", "view_grade", "view_knowledgesource", "view_academicevent",
            "add_academicevent", "change_academicevent", "delete_academicevent",
            "view_questionblueprint", "view_blueprintitem",
        ))
        self.stdout.write("Role: Exam Controller (generates and sees confidential final papers, manages the calendar)")

        # Confidentiality: only the exam controller role keeps the final-paper permission.
        final = Permission.objects.filter(content_type__app_label="questionbank", codename=FINAL).first()
        if final:
            for group in Group.objects.exclude(pk=controller.pk).filter(permissions=final):
                group.permissions.remove(final)
                self.stdout.write(self.style.WARNING(f"Removed final-paper access from role: {group.name}"))

        self.stdout.write(self.style.SUCCESS("Academic roles ready."))
