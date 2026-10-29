from django.apps import AppConfig
from django.db.models.signals import post_migrate


class LearningConfig(AppConfig):
    name = 'learning'

    def ready(self):
        from django.contrib.auth.models import Group

        from .roles import create_missing_roles

        # Staff think in terms of roles (Head of Department, Teacher...), not Django "groups".
        # Display-only; the user form and filter labels are set in learning/admin.py.
        Group._meta.verbose_name = "role"
        Group._meta.verbose_name_plural = "roles"

        # Predefined roles appear on a fresh install; existing (possibly edited) roles are left alone.
        post_migrate.connect(create_missing_roles, sender=self, dispatch_uid="learning.create_missing_roles")
