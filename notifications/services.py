"""Create in-app notifications. Call these from the places where something happens."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q

from .models import Notification


def notify(users, title, *, body="", url="", kind=Notification.Kind.INFO, dedupe_key="", exclude=None):
    """Notify one user or an iterable of users. With a dedupe_key, each user gets it at most once."""
    if users is None:
        return
    if not hasattr(users, "__iter__"):
        users = [users]
    for user in {u for u in users if u is not None and u.is_active and u != exclude}:
        if dedupe_key:
            Notification.objects.get_or_create(
                recipient=user, dedupe_key=dedupe_key,
                defaults={"title": title[:200], "body": body[:300], "url": url, "kind": kind},
            )
        else:
            Notification.objects.create(recipient=user, title=title[:200], body=body[:300], url=url, kind=kind)


def users_with_perm(perm):
    """Active users who hold "app_label.codename" directly, through a role, or as superuser."""
    app_label, codename = perm.split(".")
    permission = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
    query = Q(is_superuser=True)
    if permission:
        query |= Q(user_permissions=permission) | Q(groups__permissions=permission)
    return list(get_user_model().objects.filter(query, is_active=True).distinct())
