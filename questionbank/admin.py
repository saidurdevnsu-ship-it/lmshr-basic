from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html_join
from django.utils.http import urlencode

from .ai import GenerationError, generate_questions
from .forms import GenerateQuestionsForm, KnowledgeSourceForm
from .models import Grade, KnowledgeSource, Question, Subject


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)


@admin.register(KnowledgeSource)
class KnowledgeSourceAdmin(admin.ModelAdmin):
    form = KnowledgeSourceForm
    list_display = ("title", "subject", "grade", "is_active", "uploaded_by", "created_at")
    list_filter = ("subject", "grade", "is_active")
    search_fields = ("title",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    change_list_template = "admin/questionbank/question/change_list.html"
    list_display = ("__str__", "subject", "grade", "question_type", "difficulty", "status", "ai_generated")
    list_filter = ("status", "subject", "grade", "question_type", "difficulty", "ai_generated")
    search_fields = ("text", "answer", "topic", "source_reference")
    readonly_fields = ("ai_generated", "created_by", "created_at", "updated_at", "options_preview")
    actions = ("approve", "reject")
    fieldsets = (
        (None, {"fields": ("subject", "grade", "topic", "question_type", "difficulty", "status")}),
        ("Question", {"fields": ("text", "options", "options_preview", "answer", "explanation", "source_reference")}),
        ("History", {"fields": ("ai_generated", "created_by", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Options")
    def options_preview(self, obj):
        if not obj.options:
            return "—"
        return format_html_join("", "<div>{}. {}</div>", ((chr(65 + i), o) for i, o in enumerate(obj.options)))

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected questions", permissions=["change"])
    def approve(self, request, queryset):
        updated = queryset.update(status=Question.Status.APPROVED)
        self.message_user(request, f"Approved {updated} question(s).", messages.SUCCESS)

    @admin.action(description="Reject selected questions", permissions=["change"])
    def reject(self, request, queryset):
        updated = queryset.update(status=Question.Status.REJECTED)
        self.message_user(request, f"Rejected {updated} question(s).", messages.WARNING)

    def get_urls(self):
        return [
            path("generate/", self.admin_site.admin_view(self.generate_view), name="questionbank_question_generate"),
            *super().get_urls(),
        ]

    def generate_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        form = GenerateQuestionsForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            try:
                created = generate_questions(**data, user=request.user)
            except GenerationError as exc:
                form.add_error(None, str(exc))
            else:
                self.message_user(
                    request,
                    f"Generated {len(created)} {data['subject']} question(s) for {data['grade']}. "
                    "They're saved as drafts. Review them and approve the ones you want to keep.",
                    messages.SUCCESS,
                )
                changelist = reverse("admin:questionbank_question_changelist")
                query = urlencode({
                    "subject__id__exact": data["subject"].pk,
                    "grade__id__exact": data["grade"].pk,
                    "status__exact": Question.Status.DRAFT,
                })
                return redirect(f"{changelist}?{query}")

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Generate questions with AI",
            "form": form,
            "sources_by_pair": self._source_counts(),
            "can_add_source": request.user.has_perm("questionbank.add_knowledgesource"),
        }
        return TemplateResponse(request, "admin/questionbank/question/generate.html", context)

    @staticmethod
    def _source_counts():
        counts = {}
        for subject_id, grade_id in KnowledgeSource.objects.filter(is_active=True).values_list("subject_id", "grade_id"):
            key = f"{subject_id}:{grade_id}"
            counts[key] = counts.get(key, 0) + 1
        return counts
