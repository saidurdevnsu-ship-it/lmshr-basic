from django.apps import AppConfig


class LearningConfig(AppConfig):
    name = 'learning'

    def ready(self):
        from django.contrib.auth.models import Group

        # Staff think in terms of roles (Head of Department, Teacher...), not Django "groups".
        # Display-only; the user form and filter labels are set in learning/admin.py.
        Group._meta.verbose_name = "role"
        Group._meta.verbose_name_plural = "roles"
