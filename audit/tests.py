from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AuditEvent

Action = AuditEvent.Action


class AuditLogTests(TestCase):
    def setUp(self):
        self.boss = get_user_model().objects.create_superuser("boss", "boss@example.com", "Pw-12345!")

    def test_sign_in_and_failed_sign_in_are_logged_without_password(self):
        self.client.post(reverse("login"), {"username": "boss", "password": "wrong-pw"})
        self.client.post(reverse("login"), {"username": "boss", "password": "Pw-12345!"})
        failed = AuditEvent.objects.get(action=Action.LOGIN_FAILED)
        self.assertIn("boss", failed.details)
        self.assertNotIn("wrong-pw", failed.details)
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGIN, actor=self.boss).exists())

    def test_admin_edits_are_logged(self):
        self.client.force_login(self.boss)
        self.client.post(reverse("admin:questionbank_subject_add"), {"name": "Physics", "code": "PHY"})
        entry = AuditEvent.objects.get(action=Action.ADDED)
        self.assertEqual((entry.actor_name, entry.target_type, entry.target), ("boss", "subject", "Physics"))

    def test_log_is_read_only(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(reverse("admin:audit_auditevent_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:audit_auditevent_add")).status_code, 403)
