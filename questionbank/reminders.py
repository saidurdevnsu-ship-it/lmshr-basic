"""Deadline reminders for question blueprints and calendar deadlines, created as in-app notifications."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import notify

from .models import AcademicEvent, QuestionBlueprint

# Remind 7, 3 and 1 day(s) before a deadline, then once when it's overdue.
BUCKETS = ((1, "1d"), (3, "3d"), (7, "7d"))


def _bucket(days_left):
    if days_left < 0:
        return "overdue"
    for limit, name in BUCKETS:
        if days_left <= limit:
            return name
    return None


def _when(days_left):
    if days_left < 0:
        return f"{-days_left} day{'s' if days_left != -1 else ''} overdue"
    if days_left == 0:
        return "due today"
    if days_left == 1:
        return "due tomorrow"
    return f"due in {days_left} days"


def ensure_reminders(user):
    today = timezone.localdate()

    for bp in QuestionBlueprint.objects.filter(assigned_to=user, status__in=QuestionBlueprint.EDITABLE_BY_AUTHOR):
        days_left = (bp.due_date - today).days
        bucket = _bucket(days_left)
        if bucket is None:
            continue
        notify(
            user,
            f"Question blueprint “{bp.title}”: {_when(days_left)}",
            body="Add the sections and sample questions, then submit it for HOD review so the final paper can be generated.",
            url=reverse("admin:questionbank_questionblueprint_change", args=[bp.pk]),
            kind=Notification.Kind.WARNING if bucket == "overdue" else Notification.Kind.REMINDER,
            dedupe_key=f"blueprint-due:{bp.pk}:{bucket}",
        )

    if user.has_perm("questionbank.add_question"):
        upcoming = AcademicEvent.objects.filter(
            event_type=AcademicEvent.EventType.QUESTION_DEADLINE,
            start_date__range=(today, today + timedelta(days=7)),
        ).select_related("subject", "grade")
        for event in upcoming:
            scope = " · ".join(str(x) for x in (event.subject, event.grade) if x)
            notify(
                user,
                f"Question deadline: {event.title} ({_when((event.start_date - today).days)})",
                body=(f"{scope}. " if scope else "") + "Make sure your questions are generated and reviewed in time.",
                url=reverse("admin:questionbank_question_generate"),
                kind=Notification.Kind.REMINDER,
                dedupe_key=f"event-deadline:{event.pk}",
            )
