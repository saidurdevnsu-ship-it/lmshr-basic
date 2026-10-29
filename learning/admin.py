from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm
from django.contrib.auth.models import Group, User

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


# ---------- No privilege escalation ----------
# Anyone who isn't a super admin can only hand out permissions they already hold: they can't make anyone (themselves
# included) a super admin, can't give roles stronger than their own, can't edit accounts stronger than their own
# (changing such an account's email would let them reset its password), and can't change what a role allows.

def _perm_names(permissions):
    return {f"{p.content_type.app_label}.{p.codename}" for p in permissions}


def grantable_roles(user):
    """Roles this user may give to others: all for super admins, otherwise roles within the user's own permissions."""
    roles = Group.objects.all()
    if user.is_superuser:
        return roles
    mine = user.get_all_permissions()
    allowed = [g.pk for g in roles.prefetch_related("permissions__content_type")
               if _perm_names(g.permissions.all()) <= mine]
    return roles.filter(pk__in=allowed)


def can_manage_account(user, target):
    if user.is_superuser:
        return True
    return not target.is_superuser and target.get_all_permissions() <= user.get_all_permissions()


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(Group)
class RoleAdmin(BaseGroupAdmin):
    """Only super admins create roles or change what they allow; others can look."""

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django's user admin, with "groups" presented as roles and no way to gain more permissions than you hold."""

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

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or can_manage_account(request.user, obj))

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or can_manage_account(request.user, obj))

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        if request.user.is_superuser:
            return readonly
        return (*readonly, "is_superuser", "is_staff", "user_permissions", "last_login", "date_joined")

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
            if can_manage_account(request.user, user):
                self._welcome(request, user)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        formfield = super().formfield_for_manytomany(db_field, request, **kwargs)
        if db_field.name == "groups":
            formfield.queryset = grantable_roles(request.user)
            formfield.label = "Roles"
            formfield.help_text = (
                "The roles this user has. A user gets all permissions granted to each of their roles."
            )
        return formfield
