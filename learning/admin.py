from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm
from django.contrib.auth.models import User

from notifications.make import send_event, user_created_data

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
            # Roles are saved by now, so the email and the Make event can list them.
            self._welcome(request, form.instance)
            send_event("user.created", user_created_data(form.instance, created_by=request.user))

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
