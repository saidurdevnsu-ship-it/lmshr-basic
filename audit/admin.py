from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only: entries can't be added, edited or deleted, so the log can be trusted."""

    list_display = ("created_at", "actor_name", "action", "target_type", "target", "ip_address")
    list_filter = ("action", "target_type", "created_at")
    search_fields = ("actor_name", "target", "details")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
