"""Blueprint workflow: teacher/SME → HOD review → exam controller → confidential final paper.

Notifications about the final paper never include its questions, and links for teachers and HODs point to the
blueprint, which they're allowed to see.
"""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import notify, users_with_perm

from .models import FinalPaper, QuestionBlueprint

Status = QuestionBlueprint.Status
FINAL_PERM = "questionbank.manage_final_papers"


class WorkflowError(Exception):
    pass


def can_review(user):
    return user.has_perm("questionbank.review_blueprint")


def can_manage_final(user):
    return user.is_active and (user.is_superuser or user.has_perm(FINAL_PERM))


def _url(bp):
    return reverse("admin:questionbank_questionblueprint_change", args=[bp.pk])


def _name(user):
    return user.get_full_name() or user.get_username()


def notify_assigned(bp, by):
    if bp.assigned_to_id and bp.assigned_to != by:
        notify(bp.assigned_to, f"New question blueprint assigned: {bp.title}",
               body=f"{bp.subject} · {bp.grade} · due {bp.due_date:%d %b %Y}. Upload sample questions and the paper structure.",
               url=_url(bp), kind=Notification.Kind.REMINDER)


def problems_before_submit(bp):
    problems = []
    if not bp.items.exists():
        problems.append("Add at least one section (question type, how many, marks) before submitting.")
    return problems


@transaction.atomic
def submit(bp, user):
    if bp.status not in QuestionBlueprint.EDITABLE_BY_AUTHOR:
        raise WorkflowError("Only draft or returned blueprints can be submitted.")
    problems = problems_before_submit(bp)
    if problems:
        raise WorkflowError(" ".join(problems))
    bp.status = Status.IN_REVIEW
    bp.submitted_at = timezone.now()
    bp.save()
    notify(users_with_perm("questionbank.review_blueprint"), f"Blueprint to review: {bp.title}",
           body=f"From {_name(user)} · {bp.total_questions} questions · {bp.total_marks} marks.",
           url=_url(bp), kind=Notification.Kind.APPROVAL, exclude=user)


def reviews_own(bp, user):
    """A HOD can't review a blueprint they wrote themselves; another HOD (or the super admin) must."""
    return bp.assigned_to_id == user.pk and not user.is_superuser


@transaction.atomic
def approve(bp, user, note=""):
    if bp.status != Status.IN_REVIEW:
        raise WorkflowError("Only blueprints waiting for review can be approved.")
    if reviews_own(bp, user):
        raise WorkflowError("You wrote this blueprint, so another HOD has to review it.")
    bp.status = Status.APPROVED
    bp.reviewed_by, bp.reviewed_at = user, timezone.now()
    if note:
        bp.review_note = note
    bp.save()
    notify(bp.assigned_to, f"Blueprint approved: {bp.title}",
           body="It's with the exam controller, who will prepare the final paper.",
           url=_url(bp), kind=Notification.Kind.SUCCESS, exclude=user)
    notify(users_with_perm(FINAL_PERM), f"Blueprint ready for the final paper: {bp.title}",
           body=f"{bp.subject} · {bp.grade} · approved by {_name(user)}. Generate the final paper with AI.",
           url=_url(bp), kind=Notification.Kind.APPROVAL, exclude=user)


@transaction.atomic
def return_to_author(bp, user, note):
    if bp.status != Status.IN_REVIEW:
        raise WorkflowError("Only blueprints waiting for review can be returned.")
    if reviews_own(bp, user):
        raise WorkflowError("You wrote this blueprint, so another HOD has to review it.")
    if not note.strip():
        raise WorkflowError("Add a comment so the teacher knows what to change.")
    bp.status = Status.RETURNED
    bp.reviewed_by, bp.reviewed_at, bp.review_note = user, timezone.now(), note
    bp.save()
    notify(bp.assigned_to, f"Changes requested: {bp.title}", body=note,
           url=_url(bp), kind=Notification.Kind.WARNING, exclude=user)


@transaction.atomic
def lock_final(paper, user):
    if paper.status == FinalPaper.Status.LOCKED:
        raise WorkflowError("This final paper is already locked.")
    if paper.is_generating:
        raise WorkflowError("Claude is still writing this paper. Lock it once it's ready.")
    if not paper.questions.exists():
        raise WorkflowError("Generate the paper before locking it.")
    paper.status = FinalPaper.Status.LOCKED
    paper.locked_by, paper.locked_at = user, timezone.now()
    paper.save()
    bp = paper.blueprint
    bp.status = Status.FINALIZED
    bp.save(update_fields=["status", "updated_at"])
    # Teachers and HODs learn that it's done, nothing more.
    notify([bp.assigned_to, bp.reviewed_by], f"Final paper prepared: {bp.title}",
           body="The exam controller has finalized the paper. Its questions stay confidential.",
           url=_url(bp), kind=Notification.Kind.SUCCESS, exclude=user)
