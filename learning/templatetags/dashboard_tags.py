from django import template
from django.contrib import admin
from django.db.models import Q
from django.utils import timezone

from questionbank.models import AcademicEvent, KnowledgeSource, Question, QuestionBlueprint
from questionbank.workflow import can_manage_final, can_review

register = template.Library()


def _visible_queryset(request, model):
    """The model's admin queryset for this user, or None if they can't view it.

    Going through the ModelAdmin keeps the dashboard numbers scoped exactly like
    the changelists (e.g. teachers only count their own blueprints).
    """
    model_admin = admin.site.get_model_admin(model)
    if not model_admin.has_view_permission(request):
        return None
    return model_admin.get_queryset(request)


@register.simple_tag(takes_context=True)
def dashboard_stats(context):
    request = context["request"]
    stats = {}

    questions = _visible_queryset(request, Question)
    if questions is not None:
        stats["questions_total"] = questions.count()
        stats["questions_approved"] = questions.filter(status=Question.Status.APPROVED).count()
        stats["questions_draft"] = questions.filter(status=Question.Status.DRAFT).count()

    user = request.user
    blueprints = _visible_queryset(request, QuestionBlueprint)
    if blueprints is not None:
        bp = blueprints.select_related("subject", "grade", "assigned_to")
        rows = list(bp.filter(Q(assigned_to=user), status__in=QuestionBlueprint.EDITABLE_BY_AUTHOR)[:6])
        if can_review(user):
            rows += list(bp.filter(status=QuestionBlueprint.Status.IN_REVIEW).exclude(pk__in=[r.pk for r in rows])[:6])
        if can_manage_final(user):
            rows += list(bp.filter(status=QuestionBlueprint.Status.APPROVED).exclude(pk__in=[r.pk for r in rows])[:6])
        today = timezone.localdate()
        for r in rows:
            r.days_left = (r.due_date - today).days
        stats["exam_prep"] = rows

    events = _visible_queryset(request, AcademicEvent)
    if events is not None:
        stats["upcoming_events"] = list(events.filter(start_date__gte=timezone.localdate())[:5])

    sources = _visible_queryset(request, KnowledgeSource)
    if sources is not None:
        stats["books_total"] = sources.filter(is_active=True).count()

    return stats
