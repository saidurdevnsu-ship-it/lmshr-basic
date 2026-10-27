from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services
from .forms import GeneratePayslipsForm, LeaveRequestForm, MarkAttendanceDateForm, active_employees
from .models import (
    Attendance, Department, Designation, Employee, Holiday, LeaveRequest, LeaveType, NOCRequest, Payslip,
    ReviewStatus,
)


def is_hr_manager(user):
    return user.is_superuser or user.has_perm("hr.manage_hr")


def own_employee(request):
    return getattr(request.user, "employee", None)


class OwnRecordsMixin:
    """HR managers see everyone; other staff only see records belonging to their own employee profile."""

    employee_lookup = "employee"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_hr_manager(request.user):
            return qs
        employee = own_employee(request)
        if employee is None:
            return qs.none()
        return qs.filter(**{self.employee_lookup: employee})

    def get_list_filter(self, request):
        filters = super().get_list_filter(request)
        if is_hr_manager(request.user):
            return filters
        return [f for f in filters if not (isinstance(f, str) and f.startswith("employee"))]


# ---------- Setup ----------

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "date")
    date_hierarchy = "date"


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "days_per_year", "is_paid")


# ---------- Employees ----------

@admin.register(Employee)
class EmployeeAdmin(OwnRecordsMixin, admin.ModelAdmin):
    employee_lookup = "pk"
    list_display = ("employee_id", "full_name", "department", "designation", "joining_date", "gross_display", "is_active")
    list_filter = ("is_active", "department", "designation")
    search_fields = ("employee_id", "user__username", "user__first_name", "user__last_name", "phone")
    autocomplete_fields = ("user",)
    list_select_related = ("user", "department", "designation")
    fieldsets = (
        (None, {"fields": ("user", "employee_id", "department", "designation", "joining_date", "is_active")}),
        ("Contact", {"fields": ("phone", "address")}),
        ("Bank", {"fields": ("bank_name", "bank_account")}),
        ("Monthly salary", {"fields": (
            "basic_salary", "house_rent", "medical_allowance", "conveyance_allowance", "other_allowance",
            "provident_fund_rate", "monthly_tax",
        )}),
    )

    def get_queryset(self, request):
        qs = admin.ModelAdmin.get_queryset(self, request)
        if is_hr_manager(request.user):
            return qs
        employee = own_employee(request)
        return qs.filter(pk=employee.pk) if employee else qs.none()

    @admin.display(description="Gross / month", ordering="basic_salary")
    def gross_display(self, obj):
        return f"{settings.HR_CURRENCY} {obj.gross_salary:,.2f}"


# ---------- Attendance ----------

@admin.register(Attendance)
class AttendanceAdmin(OwnRecordsMixin, admin.ModelAdmin):
    change_list_template = "admin/hr/attendance/change_list.html"
    list_display = ("date", "employee", "status_badge", "check_in", "check_out", "note")
    list_filter = ("status", "date", "employee__department", "employee")
    date_hierarchy = "date"
    search_fields = ("employee__employee_id", "employee__user__first_name", "employee__user__last_name")
    list_select_related = ("employee__user",)
    autocomplete_fields = ("employee",)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return format_html('<span class="hr-badge hr-badge--{}">{}</span>', obj.status, obj.get_status_display())

    def has_add_permission(self, request):
        return is_hr_manager(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return is_hr_manager(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return is_hr_manager(request.user) and super().has_delete_permission(request, obj)

    def get_urls(self):
        view = self.admin_site.admin_view
        return [
            path("check-in/", view(require_POST(self.check_in_view)), name="hr_check_in"),
            path("check-out/", view(require_POST(self.check_out_view)), name="hr_check_out"),
            path("mark/", view(self.mark_view), name="hr_mark_attendance"),
            *super().get_urls(),
        ]

    def _back(self, request):
        target = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            target = reverse("admin:app_list", args=["hr"])
        return redirect(target)

    def check_in_view(self, request):
        employee = own_employee(request)
        if employee is None:
            self.message_user(request, "Your HR profile isn't set up yet. Ask HR to add you as an employee.", messages.ERROR)
            return self._back(request)
        record, created = services.check_in(employee)
        if created:
            late = " You're marked late today." if record.status == Attendance.Status.LATE else ""
            self.message_user(request, f"Checked in at {record.check_in:%I:%M %p}.{late}", messages.SUCCESS)
        else:
            self.message_user(request, "You've already checked in today.", messages.INFO)
        return self._back(request)

    def check_out_view(self, request):
        employee = own_employee(request)
        record = services.check_out(employee) if employee else None
        if record is None:
            self.message_user(request, "Check in first, then you can check out.", messages.ERROR)
        else:
            self.message_user(request, f"Checked out at {record.check_out:%I:%M %p}. Have a good evening!", messages.SUCCESS)
        return self._back(request)

    def mark_view(self, request):
        if not (is_hr_manager(request.user) and self.has_view_permission(request)):
            raise PermissionDenied
        date_form = MarkAttendanceDateForm(request.GET or {"date": timezone.localdate()})
        day = date_form.cleaned_data["date"] if date_form.is_valid() else timezone.localdate()
        employees = list(active_employees())
        existing = {a.employee_id: a for a in Attendance.objects.filter(date=day, employee__in=employees)}

        if request.method == "POST":
            saved = 0
            for emp in employees:
                status = request.POST.get(f"status_{emp.pk}")
                if status not in Attendance.Status.values:
                    continue
                Attendance.objects.update_or_create(
                    employee=emp, date=day,
                    defaults={"status": status, "note": request.POST.get(f"note_{emp.pk}", "")[:255]},
                )
                saved += 1
            self.message_user(request, f"Saved attendance for {saved} employee(s) on {day:%d %b %Y}.", messages.SUCCESS)
            return redirect(f"{reverse('admin:hr_mark_attendance')}?date={day.isoformat()}")

        is_workday = bool(services.working_days(day, day))
        rows = [{"employee": e, "record": existing.get(e.pk)} for e in employees]
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Mark attendance",
            "day": day,
            "is_workday": is_workday,
            "rows": rows,
            "statuses": Attendance.Status.choices,
        }
        return TemplateResponse(request, "admin/hr/attendance/mark.html", context)


# ---------- Leave ----------

@admin.register(LeaveRequest)
class LeaveRequestAdmin(OwnRecordsMixin, admin.ModelAdmin):
    form = LeaveRequestForm
    list_display = ("employee", "leave_type", "start_date", "end_date", "days", "status_badge", "created_at")
    list_filter = ("status", "leave_type", "employee__department", "employee")
    search_fields = ("employee__employee_id", "employee__user__first_name", "employee__user__last_name", "reason")
    list_select_related = ("employee__user", "leave_type")
    autocomplete_fields = ("employee",)
    actions = ("approve_selected", "reject_selected", "cancel_selected")

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return format_html('<span class="hr-badge hr-badge--{}">{}</span>', obj.status, obj.get_status_display())

    def get_fields(self, request, obj=None):
        fields = ["leave_type", "start_date", "end_date", "reason"]
        if is_hr_manager(request.user):
            fields = ["employee", *fields, "review_note"]
        if obj:
            fields += ["days", "status", "reviewed_by", "reviewed_at"]
            if not is_hr_manager(request.user):
                fields.append("review_note")
        return fields

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        readonly = ["days", "status", "reviewed_by", "reviewed_at"]
        if not is_hr_manager(request.user) or obj.status != ReviewStatus.PENDING:
            readonly += ["employee", "leave_type", "start_date", "end_date", "reason", "review_note"]
        return readonly

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.own_employee = None if is_hr_manager(request.user) else own_employee(request)
        return form

    def add_view(self, request, form_url="", extra_context=None):
        if not is_hr_manager(request.user) and own_employee(request) is None:
            self.message_user(request, "Your HR profile isn't set up yet. Ask HR to add you as an employee.", messages.ERROR)
            return redirect(reverse("admin:app_list", args=["hr"]))
        return super().add_view(request, form_url, extra_context)

    def has_change_permission(self, request, obj=None):
        # Employees can open their requests but only HR edits them (and only while pending).
        if not is_hr_manager(request.user):
            return False
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if not change and not is_hr_manager(request.user):
            obj.employee = own_employee(request)
        obj.days = len(services.working_days(obj.start_date, obj.end_date))
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not is_hr_manager(request.user):
            actions.pop("approve_selected", None)
            actions.pop("reject_selected", None)
        return actions

    def _review(self, request, queryset, approve):
        done = 0
        for leave in queryset.filter(status=ReviewStatus.PENDING).select_related("employee", "leave_type"):
            services.review_leave(leave, approve=approve, reviewer=request.user)
            done += 1
        verb = "Approved" if approve else "Rejected"
        self.message_user(request, f"{verb} {done} pending leave request(s).", messages.SUCCESS if done else messages.WARNING)

    @admin.action(description="Approve selected leave")
    def approve_selected(self, request, queryset):
        self._review(request, queryset, approve=True)

    @admin.action(description="Reject selected leave")
    def reject_selected(self, request, queryset):
        self._review(request, queryset, approve=False)

    @admin.action(description="Cancel selected (pending only)")
    def cancel_selected(self, request, queryset):
        n = queryset.filter(status=ReviewStatus.PENDING).update(status=ReviewStatus.CANCELLED)
        self.message_user(request, f"Cancelled {n} pending request(s).", messages.SUCCESS if n else messages.WARNING)


# ---------- NOC ----------

@admin.register(NOCRequest)
class NOCRequestAdmin(OwnRecordsMixin, admin.ModelAdmin):
    list_display = ("employee", "purpose", "created_at", "status_badge", "reference_no", "letter_link")
    list_filter = ("status", "purpose", "employee__department", "employee")
    search_fields = ("employee__employee_id", "employee__user__first_name", "employee__user__last_name", "reference_no")
    list_select_related = ("employee__user",)
    autocomplete_fields = ("employee",)
    actions = ("approve_selected", "reject_selected", "cancel_selected")

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return format_html('<span class="hr-badge hr-badge--{}">{}</span>', obj.status, obj.get_status_display())

    @admin.display(description="Letter")
    def letter_link(self, obj):
        if obj.status != ReviewStatus.APPROVED:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Print letter</a>', reverse("admin:hr_noc_letter", args=[obj.pk]))

    def get_fields(self, request, obj=None):
        fields = ["purpose", "addressed_to", "details", "travel_from", "travel_to"]
        if is_hr_manager(request.user):
            fields = ["employee", *fields, "review_note"]
        if obj:
            fields += ["status", "reference_no", "reviewed_by", "reviewed_at"]
            if not is_hr_manager(request.user):
                fields.append("review_note")
        return fields

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        readonly = ["status", "reference_no", "reviewed_by", "reviewed_at"]
        if not is_hr_manager(request.user) or obj.status != ReviewStatus.PENDING:
            readonly += ["employee", "purpose", "addressed_to", "details", "travel_from", "travel_to", "review_note"]
        return readonly

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for name in ("travel_from", "travel_to"):
            if name in form.base_fields:
                form.base_fields[name].widget = admin.widgets.AdminDateWidget()
        return form

    def add_view(self, request, form_url="", extra_context=None):
        if not is_hr_manager(request.user) and own_employee(request) is None:
            self.message_user(request, "Your HR profile isn't set up yet. Ask HR to add you as an employee.", messages.ERROR)
            return redirect(reverse("admin:app_list", args=["hr"]))
        return super().add_view(request, form_url, extra_context)

    def has_change_permission(self, request, obj=None):
        if not is_hr_manager(request.user):
            return False
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if not change and not is_hr_manager(request.user):
            obj.employee = own_employee(request)
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not is_hr_manager(request.user):
            actions.pop("approve_selected", None)
            actions.pop("reject_selected", None)
        return actions

    def _review(self, request, queryset, approve):
        done = 0
        for noc in queryset.filter(status=ReviewStatus.PENDING):
            services.review_noc(noc, approve=approve, reviewer=request.user)
            done += 1
        verb = "Approved" if approve else "Rejected"
        self.message_user(request, f"{verb} {done} pending NOC request(s).", messages.SUCCESS if done else messages.WARNING)

    @admin.action(description="Approve selected NOC requests")
    def approve_selected(self, request, queryset):
        self._review(request, queryset, approve=True)

    @admin.action(description="Reject selected NOC requests")
    def reject_selected(self, request, queryset):
        self._review(request, queryset, approve=False)

    @admin.action(description="Cancel selected (pending only)")
    def cancel_selected(self, request, queryset):
        n = queryset.filter(status=ReviewStatus.PENDING).update(status=ReviewStatus.CANCELLED)
        self.message_user(request, f"Cancelled {n} pending request(s).", messages.SUCCESS if n else messages.WARNING)

    def get_urls(self):
        return [
            path("<int:pk>/letter/", self.admin_site.admin_view(self.letter_view), name="hr_noc_letter"),
            *super().get_urls(),
        ]

    def letter_view(self, request, pk):
        noc = get_object_or_404(self.get_queryset(request).select_related("employee__user", "employee__designation",
                                                                            "employee__department"), pk=pk)
        if noc.status != ReviewStatus.APPROVED:
            raise PermissionDenied
        return TemplateResponse(request, "hr/noc_letter.html", {"noc": noc, "employee": noc.employee, **_letterhead()})


# ---------- Payroll ----------

def _letterhead():
    return {"company_name": settings.HR_COMPANY_NAME, "company_address": settings.HR_COMPANY_ADDRESS,
            "currency": settings.HR_CURRENCY}


@admin.register(Payslip)
class PayslipAdmin(OwnRecordsMixin, admin.ModelAdmin):
    change_list_template = "admin/hr/payslip/change_list.html"
    list_display = ("employee", "period", "gross_display", "deduction_display", "net_display", "status_badge", "print_link")
    list_filter = ("status", "year", "month", "employee__department", "employee")
    search_fields = ("employee__employee_id", "employee__user__first_name", "employee__user__last_name")
    list_select_related = ("employee__user",)
    actions = ("finalize_selected",)
    fieldsets = (
        (None, {"fields": ("employee", "year", "month", "status")}),
        ("Earnings", {"fields": ("basic_salary", "house_rent", "medical_allowance", "conveyance_allowance",
                                 "other_allowance", "gross_salary")}),
        ("Attendance", {"fields": ("days_in_month", "working_days", "absent_days", "unpaid_leave_days")}),
        ("Deductions", {"fields": ("absence_deduction", "provident_fund", "tax", "other_deduction", "total_deduction")}),
        (None, {"fields": ("net_pay",)}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_hr_manager(request.user):
            return qs
        # Employees only see payslips once HR has finalized them.
        return qs.filter(status=Payslip.Status.FINAL)

    def get_readonly_fields(self, request, obj=None):
        everything = [f.name for f in Payslip._meta.fields if f.name not in ("id",)]
        if obj and obj.status == Payslip.Status.DRAFT and is_hr_manager(request.user):
            return [f for f in everything if f != "other_deduction"]
        return everything

    def has_add_permission(self, request):
        return False  # payslips are created with "Generate pay slips"

    def has_change_permission(self, request, obj=None):
        return is_hr_manager(request.user) and super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        obj.recalculate_totals()
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not is_hr_manager(request.user):
            actions.pop("finalize_selected", None)
        return actions

    @admin.display(description="Period", ordering="year")
    def period(self, obj):
        return obj.period_label

    @admin.display(description="Gross", ordering="gross_salary")
    def gross_display(self, obj):
        return f"{obj.gross_salary:,.2f}"

    @admin.display(description="Deductions", ordering="total_deduction")
    def deduction_display(self, obj):
        return f"{obj.total_deduction:,.2f}"

    @admin.display(description="Net pay", ordering="net_pay")
    def net_display(self, obj):
        return format_html("<strong>{} {}</strong>", settings.HR_CURRENCY, f"{obj.net_pay:,.2f}")

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return format_html('<span class="hr-badge hr-badge--{}">{}</span>', obj.status, obj.get_status_display())

    @admin.display(description="")
    def print_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">View / print</a>', reverse("admin:hr_payslip_print", args=[obj.pk]))

    @admin.action(description="Finalize selected (employees can then see them)")
    def finalize_selected(self, request, queryset):
        n = queryset.filter(status=Payslip.Status.DRAFT).update(status=Payslip.Status.FINAL)
        self.message_user(request, f"Finalized {n} pay slip(s).", messages.SUCCESS if n else messages.WARNING)

    def get_urls(self):
        view = self.admin_site.admin_view
        return [
            path("generate/", view(self.generate_view), name="hr_payslip_generate"),
            path("<int:pk>/print/", view(self.print_view), name="hr_payslip_print"),
            *super().get_urls(),
        ]

    def generate_view(self, request):
        if not is_hr_manager(request.user):
            raise PermissionDenied
        form = GeneratePayslipsForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            year, month = form.cleaned_data["year"], form.cleaned_data["month"]
            created, updated, skipped = services.generate_payslips(year, month, request.user)
            msg = f"Pay slips for {timezone.datetime(year, month, 1):%B %Y}: {created} created, {updated} refreshed"
            if skipped:
                msg += f", {skipped} already finalized (left unchanged)"
            self.message_user(request, msg + ". Review the drafts, then finalize them.", messages.SUCCESS)
            return redirect(f"{reverse('admin:hr_payslip_changelist')}?year={year}&month={month}")
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Generate pay slips",
            "form": form,
            "employee_count": Employee.objects.filter(is_active=True).count(),
        }
        return TemplateResponse(request, "admin/hr/payslip/generate.html", context)

    def print_view(self, request, pk):
        slip = get_object_or_404(
            self.get_queryset(request).select_related("employee__user", "employee__department", "employee__designation"),
            pk=pk,
        )
        return TemplateResponse(request, "hr/payslip_print.html", {"slip": slip, "employee": slip.employee, **_letterhead()})
