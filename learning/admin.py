from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Course, CourseModule, LearningActivity
from .welcome import send_welcome_email


class NewUserForm(AdminUserCreationForm):
    """Add-user form that also collects name, email and roles, so the welcome email can go out at once."""

    class Meta(AdminUserCreationForm.Meta):
        fields = ("username", "first_name", "last_name", "email", "groups")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["email"].help_text = "The welcome email, with a link to set a password, is sent here."


class RoleListFilter(admin.RelatedFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = "role"


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django's user admin, with "groups" presented as roles."""

    list_filter = ("is_staff", "is_superuser", "is_active", ("groups", RoleListFilter))
    add_form = NewUserForm
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "first_name", "last_name", "email")}),
        ("Roles", {"classes": ("wide",), "fields": ("groups",)}),
        ("Password", {
            "classes": ("wide",),
            "fields": ("usable_password", "password1", "password2"),
            "description": "You can leave the password off: the welcome email lets the person set their own.",
        }),
    )
    actions = ("resend_welcome",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.is_staff = True  # everyone signs in to the STS Pulse dashboard
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not change:
            # Roles are saved by now, so the email can list them.
            self._welcome(request, form.instance)

    def _welcome(self, request, user):
        if not user.email:
            self.message_user(request, f"No email address for {user}, so no welcome email was sent.", messages.WARNING)
        elif send_welcome_email(user, request):
            self.message_user(request, f"Welcome email sent to {user.email}.", messages.SUCCESS)
        else:
            self.message_user(request, f"The account was created, but the welcome email to {user.email} couldn't be sent. "
                                       "Check the email settings, then use “Resend welcome email”.", messages.WARNING)

    @admin.action(description="Resend welcome email", permissions=["change"])
    def resend_welcome(self, request, queryset):
        for user in queryset:
            self._welcome(request, user)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        formfield = super().formfield_for_manytomany(db_field, request, **kwargs)
        if db_field.name == "groups":
            formfield.label = "Roles"
            formfield.help_text = (
                "The roles this user has. A user gets all permissions granted to each of their roles."
            )
        return formfield


class CourseModuleInline(admin.TabularInline):
    model = CourseModule
    extra = 0
    fields = ("title", "position", "is_published")
    ordering = ("position",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "created_by", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "summary", "created_by__username", "created_by__email")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_by", "created_at", "updated_at", "published_at")
    inlines = (CourseModuleInline,)

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("created_by")
        if request.user.is_superuser or request.user.has_perm("learning.view_all_courses"):
            return queryset
        return queryset.filter(created_by=request.user)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser and not request.user.has_perm("learning.publish_course"):
            fields.append("status")
        return fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        if obj.status == Course.Status.PUBLISHED and obj.published_at is None:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)


class LearningActivityInline(admin.TabularInline):
    model = LearningActivity
    extra = 0
    # body/resource_url must be editable here: LearningActivity.clean() raises
    # errors keyed to them, which crashes a form that doesn't include them.
    fields = ("title", "activity_type", "position", "body", "resource_url", "is_published")
    ordering = ("position",)


@admin.register(CourseModule)
class CourseModuleAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "position", "is_published")
    list_filter = ("is_published", "course")
    search_fields = ("title", "course__title")
    inlines = (LearningActivityInline,)

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("course", "course__created_by")
        if request.user.is_superuser or request.user.has_perm("learning.view_all_courses"):
            return queryset
        return queryset.filter(course__created_by=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course" and not request.user.is_superuser:
            if not request.user.has_perm("learning.view_all_courses"):
                kwargs["queryset"] = Course.objects.filter(created_by=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(LearningActivity)
class LearningActivityAdmin(admin.ModelAdmin):
    list_display = ("title", "module", "activity_type", "position", "is_published")
    list_filter = ("activity_type", "is_published")
    search_fields = ("title", "module__title", "module__course__title")

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "module", "module__course", "module__course__created_by"
        )
        if request.user.is_superuser or request.user.has_perm("learning.view_all_courses"):
            return queryset
        return queryset.filter(module__course__created_by=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "module" and not request.user.is_superuser:
            if not request.user.has_perm("learning.view_all_courses"):
                kwargs["queryset"] = CourseModule.objects.filter(course__created_by=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
