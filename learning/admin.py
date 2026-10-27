from django.contrib import admin
from django.utils import timezone

from .models import Course, CourseModule, LearningActivity


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
