from django import template
from django.contrib import admin
from django.db.models import Sum

from learning.models import Course, CourseModule, LearningActivity
from questionbank.models import KnowledgeSource, Question

register = template.Library()


def _visible_queryset(request, model):
    """The model's admin queryset for this user, or None if they can't view it.

    Going through the ModelAdmin keeps the dashboard numbers scoped exactly like
    the changelists (e.g. teachers only count their own courses).
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

    sources = _visible_queryset(request, KnowledgeSource)
    if sources is not None:
        stats["books_total"] = sources.filter(is_active=True).count()

    courses =_visible_queryset(request, Course)
    if courses is not None:
        stats["courses_total"] = courses.count()
        stats["courses_published"] = courses.filter(status=Course.Status.PUBLISHED).count()
        stats["courses_draft"] = courses.filter(status=Course.Status.DRAFT).count()
        stats["recent_courses"] = list(
            courses.order_by("-updated_at")[:5]
        )

    modules = _visible_queryset(request, CourseModule)
    if modules is not None:
        stats["modules_total"] = modules.count()

    activities = _visible_queryset(request, LearningActivity)
    if activities is not None:
        stats["activities_total"] = activities.count()
        minutes = activities.aggregate(total=Sum("estimated_minutes"))["total"] or 0
        stats["learning_hours"] = round(minutes / 60, 1)

    return stats
