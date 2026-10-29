from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """One key activity: who did what, to which record, and when. Never holds final paper questions or passwords."""

    class Action(models.TextChoices):
        LOGIN = "login", "Signed in"
        LOGIN_FAILED = "login_failed", "Sign-in failed"
        LOGOUT = "logout", "Signed out"
        ADDED = "added", "Added"
        CHANGED = "changed", "Edited"
        DELETED = "deleted", "Deleted"
        QUESTIONS_GENERATED = "questions_generated", "Generated questions with AI"
        QUESTIONS_APPROVED = "questions_approved", "Approved questions"
        QUESTIONS_REJECTED = "questions_rejected", "Rejected questions"
        BLUEPRINT_SUBMITTED = "blueprint_submitted", "Submitted blueprint for review"
        BLUEPRINT_APPROVED = "blueprint_approved", "Approved blueprint"
        BLUEPRINT_RETURNED = "blueprint_returned", "Returned blueprint for changes"
        FINAL_STARTED = "final_started", "Started final paper generation"
        FINAL_GENERATED = "final_generated", "Final paper generated"
        FINAL_FAILED = "final_failed", "Final paper generation failed"
        FINAL_LOCKED = "final_locked", "Locked final paper"
        FINAL_EXPORTED = "final_exported", "Exported / printed final paper"
        LEAVE_APPROVED = "leave_approved", "Approved leave"
        LEAVE_REJECTED = "leave_rejected", "Rejected leave"
        LEAVE_CANCELLED = "leave_cancelled", "Cancelled leave"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="+")
    actor_name = models.CharField("user", max_length=150, blank=True,
                                  help_text="Kept even if the account is deleted later.")
    action = models.CharField(max_length=30, choices=Action.choices, db_index=True)
    target_type = models.CharField("record type", max_length=100, blank=True)
    target_id = models.CharField(max_length=50, blank=True)
    target = models.CharField("record", max_length=200, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField("IP address", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"

    def __str__(self):
        return f"{self.actor_name or 'Someone'} · {self.get_action_display()} · {self.target}"
