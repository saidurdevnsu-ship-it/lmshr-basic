import calendar as pycalendar
from datetime import date, timedelta

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.http import urlencode

from . import workflow
from .ai import GenerationError, claude_status, generate_final_paper, generate_questions
from .forms import GenerateQuestionsForm, KnowledgeSourceForm
from .models import (
    AcademicEvent, BlueprintItem, FinalPaper, FinalQuestion, Grade, KnowledgeSource, Question, QuestionBlueprint,
    Subject,
)
from .workflow import can_manage_final, can_review


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

        # Links from a question paper pre-fill its subject and grade (?subject=1&grade=2).
        initial = {k: request.GET[k] for k in ("subject", "grade", "topic") if request.GET.get(k)}
        form = GenerateQuestionsForm(request.POST or None, initial=initial)
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
            "claude": claude_status(),
        }
        return TemplateResponse(request, "admin/questionbank/question/generate.html", context)

    @staticmethod
    def _source_counts():
        counts = {}
        for subject_id, grade_id in KnowledgeSource.objects.filter(is_active=True).values_list("subject_id", "grade_id"):
            key = f"{subject_id}:{grade_id}"
            counts[key] = counts.get(key, 0) + 1
        return counts


# ---------- Academic calendar ----------

EVENT_COLORS = {
    AcademicEvent.EventType.TERM: "blue",
    AcademicEvent.EventType.EXAM_SERIES: "violet",
    AcademicEvent.EventType.INTERNAL_EXAM: "amber",
    AcademicEvent.EventType.QUESTION_DEADLINE: "red",
    AcademicEvent.EventType.BREAK: "teal",
    AcademicEvent.EventType.OTHER: "slate",
}


@admin.register(AcademicEvent)
class AcademicEventAdmin(admin.ModelAdmin):
    change_list_template = "admin/questionbank/academicevent/change_list.html"
    list_display = ("title", "type_badge", "qualification", "exam_series", "start_date", "end_date", "subject", "grade")
    list_filter = ("event_type", "qualification", "exam_series", "subject", "grade")
    search_fields = ("title", "description")
    date_hierarchy = "start_date"
    fieldsets = (
        (None, {"fields": ("title", "event_type", "start_date", "end_date")}),
        ("Cambridge", {"fields": ("qualification", "exam_series"),
                       "description": "Copy dates from the official Cambridge International exam timetable."}),
        ("Scope (optional)", {"fields": ("subject", "grade", "description")}),
    )

    @admin.display(description="Type", ordering="event_type")
    def type_badge(self, obj):
        return format_html('<span class="cal-chip cal-chip--{}">{}</span>', EVENT_COLORS[obj.event_type],
                           obj.get_event_type_display())

    def get_urls(self):
        return [path("calendar/", self.admin_site.admin_view(self.calendar_view), name="questionbank_calendar"),
                *super().get_urls()]

    def calendar_view(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        today = timezone.localdate()
        try:
            year, month = int(request.GET.get("year", today.year)), int(request.GET.get("month", today.month))
            first = date(year, month, 1)
        except ValueError:
            first = today.replace(day=1)
        cal = pycalendar.Calendar(firstweekday=6)  # weeks start on Sunday
        weeks = cal.monthdatescalendar(first.year, first.month)
        grid_start, grid_end = weeks[0][0], weeks[-1][-1]
        events = list(
            AcademicEvent.objects.filter(start_date__lte=grid_end)
            .filter(Q(end_date__gte=grid_start) | Q(end_date__isnull=True, start_date__gte=grid_start))
            .select_related("subject", "grade")
        )
        by_day = {}
        for e in events:
            day = max(e.start_date, grid_start)
            while day <= min(e.last_day, grid_end):
                by_day.setdefault(day, []).append({"event": e, "color": EVENT_COLORS[e.event_type],
                                                   "is_start": day == e.start_date})
                day += timedelta(days=1)
        prev_month = (first - timedelta(days=1)).replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Academic calendar",
            "month": first,
            "today": today,
            "weeks": [[{"date": d, "in_month": d.month == first.month, "events": by_day.get(d, [])} for d in w] for w in weeks],
            "prev_month": prev_month,
            "next_month": next_month,
            "legend": [(label, EVENT_COLORS[value]) for value, label in AcademicEvent.EventType.choices],
            "upcoming": AcademicEvent.objects.filter(start_date__gte=today).select_related("subject", "grade")[:8],
            "can_add": self.has_add_permission(request),
        }
        return TemplateResponse(request, "admin/questionbank/academicevent/calendar.html", context)


# ---------- Question blueprints ----------

class BlueprintItemInline(admin.TabularInline):
    model = BlueprintItem
    extra = 1
    fields = ("order", "section", "question_type", "difficulty", "topic", "count", "marks_each", "sample_question")

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "sample_question":
            field.widget.attrs.update(rows=2, cols=40)
        return field

    def _editable(self, request, obj):
        return obj is None or QuestionBlueprintAdmin.is_editable(request.user, obj)

    def has_add_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_view_permission(self, request, obj=None):
        return True


@admin.register(QuestionBlueprint)
class QuestionBlueprintAdmin(admin.ModelAdmin):
    change_form_template = "admin/questionbank/questionblueprint/change_form.html"
    list_display = ("title", "subject", "grade", "assigned_to", "due_display", "marks_display", "status_badge")
    list_filter = ("status", "subject", "grade", "exam")
    search_fields = ("title", "assigned_to__username", "assigned_to__first_name", "assigned_to__last_name")
    list_select_related = ("subject", "grade", "assigned_to")
    autocomplete_fields = ("assigned_to",)
    inlines = (BlueprintItemInline,)

    @staticmethod
    def is_editable(user, bp):
        if bp.status in (QuestionBlueprint.Status.APPROVED, QuestionBlueprint.Status.FINALIZED):
            return False
        if bp.status == QuestionBlueprint.Status.IN_REVIEW:
            return can_review(user)
        return can_review(user) or bp.assigned_to_id == user.pk

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser or can_review(user):
            return qs
        visible = Q(assigned_to=user) | Q(created_by=user)
        if can_manage_final(user):
            visible |= Q(status__in=[QuestionBlueprint.Status.APPROVED, QuestionBlueprint.Status.FINALIZED])
        return qs.filter(visible)

    def get_fieldsets(self, request, obj=None):
        main = ["title", "subject", "grade", "exam", "due_date", "duration_minutes", "language"]
        if obj is not None or can_review(request.user):
            main.insert(4, "assigned_to")
        sets = [
            (None, {"fields": main}),
            ("Samples & guidance", {"fields": ["sample_file", "instructions", "guidance"],
                                    "description": "Add each section below with an optional sample question. Claude "
                                                   "writes new questions in that style; samples are never reused."}),
        ]
        if obj:
            sets.append(("Review", {"fields": ["status", "totals", "review_note", "reviewed_by", "reviewed_at",
                                               "submitted_at"]}))
        return sets

    def get_readonly_fields(self, request, obj=None):
        always = ["status", "totals", "review_note", "reviewed_by", "reviewed_at", "submitted_at"]
        if obj is None:
            return always
        if not self.is_editable(request.user, obj):
            return always + ["title", "subject", "grade", "exam", "assigned_to", "due_date", "duration_minutes",
                             "language", "sample_file", "instructions", "guidance"]
        return always + ([] if can_review(request.user) else ["assigned_to"])

    def has_change_permission(self, request, obj=None):
        if obj is not None and not self.is_editable(request.user, obj):
            return False
        return super().has_change_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assigned_to":
            from django.contrib.auth import get_user_model
            kwargs["queryset"] = get_user_model().objects.filter(is_active=True, is_staff=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("assigned_to", request.user.pk)
        return initial

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            if not can_review(request.user):
                obj.assigned_to = request.user
        super().save_model(request, obj, form, change)
        if not change:
            workflow.notify_assigned(obj, request.user)

    @admin.display(description="Totals")
    def totals(self, obj):
        return f"{obj.total_questions} questions · {obj.total_marks} marks"

    @admin.display(description="Marks")
    def marks_display(self, obj):
        return obj.total_marks

    @admin.display(description="Due", ordering="due_date")
    def due_display(self, obj):
        late = obj.status in QuestionBlueprint.EDITABLE_BY_AUTHOR and obj.due_date < timezone.localdate()
        return format_html('<span class="{}">{}</span>', "due-late" if late else "", obj.due_date.strftime("%d %b %Y"))

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return format_html('<span class="hr-badge hr-badge--bp-{}">{}</span>', obj.status, obj.get_status_display())

    ACTIONS = {"_submit_review": "submit", "_approve": "approve", "_return": "return", "_generate_final": "generate"}

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        action = next((name for key, name in self.ACTIONS.items() if key in request.POST), None)
        if request.method == "POST" and object_id and action:
            return self._run_action(request, object_id, action)
        extra_context = extra_context or {}
        if object_id:
            bp = self.get_object(request, object_id)
            if bp:
                user = request.user
                final = FinalPaper.objects.filter(blueprint=bp).first() if can_manage_final(user) else None
                extra_context.update({
                    "bp": bp,
                    "can_submit": bp.status in QuestionBlueprint.EDITABLE_BY_AUTHOR
                    and (bp.assigned_to_id == user.pk or can_review(user)),
                    "can_review_now": bp.status == QuestionBlueprint.Status.IN_REVIEW and can_review(user),
                    "can_generate": can_manage_final(user) and bp.status == QuestionBlueprint.Status.APPROVED
                    and (final is None or final.status != FinalPaper.Status.LOCKED),
                    "final": final,
                    "is_controller": can_manage_final(user),
                    "claude": claude_status(),
                })
        return super().changeform_view(request, object_id, form_url, extra_context)

    def _run_action(self, request, object_id, action):
        bp = self.get_object(request, object_id)
        if bp is None:
            raise PermissionDenied
        user, note = request.user, request.POST.get("review_note", "")
        try:
            if action == "submit":
                if not (bp.assigned_to_id == user.pk or can_review(user)):
                    raise PermissionDenied
                workflow.submit(bp, user)
                msg = "Submitted for HOD review. You'll get a notification when it's approved or returned."
            elif action == "approve":
                if not can_review(user):
                    raise PermissionDenied
                workflow.approve(bp, user, note)
                msg = "Approved. The exam controller has been notified to prepare the final paper."
            elif action == "return":
                if not can_review(user):
                    raise PermissionDenied
                workflow.return_to_author(bp, user, note)
                msg = "Returned to the teacher with your comments."
            else:
                if not can_manage_final(user) or bp.status != QuestionBlueprint.Status.APPROVED:
                    raise PermissionDenied
                paper = generate_final_paper(bp, user)
                self.message_user(request, f"Final paper generated with {paper.questions.count()} questions. "
                                           "Review it, then lock it.", messages.SUCCESS)
                return HttpResponseRedirect(reverse("admin:questionbank_finalpaper_change", args=[paper.pk]))
        except (workflow.WorkflowError, GenerationError) as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            self.message_user(request, msg, messages.SUCCESS)
        return HttpResponseRedirect(reverse("admin:questionbank_questionblueprint_change", args=[bp.pk]))


# ---------- Confidential final papers (exam controller + superadmin only) ----------

class FinalQuestionInline(admin.StackedInline):
    model = FinalQuestion
    extra = 0
    fields = (("order", "section", "question_type", "marks"), "text", "options", "answer", "explanation", "source_reference")

    def _editable(self, request, obj):
        return can_manage_final(request.user) and obj is not None and obj.status != FinalPaper.Status.LOCKED

    def has_view_permission(self, request, obj=None):
        return can_manage_final(request.user)

    def has_add_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._editable(request, obj)


@admin.register(FinalPaper)
class FinalPaperAdmin(admin.ModelAdmin):
    """Every permission check goes through can_manage_final, so HODs and teachers can't open these pages
    even if their role has every other question bank permission."""

    change_form_template = "admin/questionbank/finalpaper/change_form.html"
    list_display = ("blueprint", "subject", "grade", "question_count", "marks", "status", "generated_at")
    list_filter = ("status", "blueprint__subject", "blueprint__grade")
    list_select_related = ("blueprint__subject", "blueprint__grade")
    readonly_fields = ("blueprint", "status", "model_used", "generated_by", "generated_at", "locked_by", "locked_at")
    fields = ("blueprint", "status", "model_used", "generated_by", "generated_at", "locked_by", "locked_at",
              "controller_notes")
    inlines = (FinalQuestionInline,)

    def has_module_permission(self, request):
        return can_manage_final(request.user)

    def has_view_permission(self, request, obj=None):
        return can_manage_final(request.user)

    def has_change_permission(self, request, obj=None):
        return can_manage_final(request.user) and (obj is None or obj.status != FinalPaper.Status.LOCKED)

    def has_add_permission(self, request):
        return False  # created from an approved blueprint

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Subject")
    def subject(self, obj):
        return obj.blueprint.subject

    @admin.display(description="Grade")
    def grade(self, obj):
        return obj.blueprint.grade

    @admin.display(description="Questions")
    def question_count(self, obj):
        return obj.questions.count()

    @admin.display(description="Marks")
    def marks(self, obj):
        return obj.total_marks

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if not can_manage_final(request.user):
            raise PermissionDenied
        if request.method == "POST" and object_id and ("_lock" in request.POST or "_regenerate" in request.POST):
            paper = get_object_or_404(FinalPaper, pk=object_id)
            try:
                if "_lock" in request.POST:
                    workflow.lock_final(paper, request.user)
                    self.message_user(request, "Locked. This is now the final paper.", messages.SUCCESS)
                else:
                    paper = generate_final_paper(paper.blueprint, request.user)
                    self.message_user(request, f"Regenerated: {paper.questions.count()} new questions.", messages.SUCCESS)
            except (workflow.WorkflowError, GenerationError) as exc:
                self.message_user(request, str(exc), messages.ERROR)
            return HttpResponseRedirect(reverse("admin:questionbank_finalpaper_change", args=[paper.pk]))
        extra_context = {**(extra_context or {}), "final": self.get_object(request, object_id) if object_id else None}
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        return [path("<int:pk>/print/", self.admin_site.admin_view(self.print_view), name="questionbank_final_print"),
                *super().get_urls()]

    def print_view(self, request, pk):
        if not can_manage_final(request.user):
            raise PermissionDenied
        paper = get_object_or_404(FinalPaper.objects.select_related("blueprint__subject", "blueprint__grade",
                                                                    "blueprint__exam"), pk=pk)
        questions = list(paper.questions.all())
        sections = []
        for q in questions:
            if not sections or sections[-1]["name"] != q.section:
                sections.append({"name": q.section, "questions": []})
            sections[-1]["questions"].append(q)
        context = {
            "paper": paper,
            "bp": paper.blueprint,
            "sections": sections,
            "total_marks": sum(q.marks for q in questions),
            "answers": request.GET.get("answers") == "1",
            "company_name": settings.HR_COMPANY_NAME,
        }
        return TemplateResponse(request, "questionbank/final_print.html", context)
