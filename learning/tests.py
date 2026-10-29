from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


class HomeTests(TestCase):
    def test_root_sends_visitors_to_sign_in(self):
        self.assertRedirects(self.client.get("/"), reverse("login"))

    def test_root_sends_signed_in_staff_to_dashboard(self):
        user = get_user_model().objects.create_user("staff", password="Pw-12345!", is_staff=True)
        self.client.force_login(user)
        self.assertRedirects(self.client.get("/"), reverse("admin:index"))

    def test_admin_login_uses_sts_sign_in_page(self):
        response = self.client.get("/admin/login/?next=/admin/hr/")
        self.assertRedirects(response, f"{reverse('login')}?next=/admin/hr/", fetch_redirect_response=False)


@override_settings(MAKE_WEBHOOK_URL="", MAKE_MAILHOOK_ADDRESS="")
class WelcomeEmailTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("boss", "boss@example.com", "Pw-12345!")
        self.client.force_login(admin)

    def add_user(self, **extra):
        data = {"username": "newbie", "first_name": "Nadia", "email": "nadia@example.com",
                "usable_password": "false", "_save": "1", **extra}
        return self.client.post(reverse("admin:auth_user_add"), data)

    def test_new_user_gets_welcome_email_without_a_password(self):
        self.add_user()
        user = get_user_model().objects.get(username="newbie")
        self.assertTrue(user.is_staff)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["nadia@example.com"])
        self.assertIn("/accounts/reset/", message.body)
        self.assertNotIn("Pw-", message.body)

    def test_email_is_required(self):
        response = self.add_user(email="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="newbie").exists())
        self.assertEqual(mail.outbox, [])

    @override_settings(MAKE_WEBHOOK_URL="https://hook.example.com/abc")
    def test_welcome_email_goes_through_make_when_webhook_is_set(self):
        with mock.patch("notifications.mail.deliver") as deliver:
            self.add_user()
        payload = deliver.call_args.args[0]
        self.assertEqual(payload["event"], "user.welcome")
        self.assertEqual(payload["data"]["to"], "nadia@example.com")
        self.assertIn("/accounts/reset/", payload["data"]["set_password_url"])
        self.assertIn("/accounts/reset/", payload["data"]["html"])
        self.assertEqual(mail.outbox, [])

    @override_settings(SITE_URL="https://lms.example.com")
    def test_welcome_links_use_site_url(self):
        self.add_user()
        self.assertIn("https://lms.example.com/accounts/reset/", mail.outbox[0].body)


@override_settings(MAKE_WEBHOOK_URL="", MAKE_MAILHOOK_ADDRESS="", SITE_URL="https://lms.example.com")
class PasswordResetTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user("nadia", "nadia@example.com", "Pw-12345!", is_staff=True)

    def test_reset_email_uses_site_url(self):
        self.client.post(reverse("password_reset"), {"email": "nadia@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://lms.example.com/accounts/reset/", mail.outbox[0].body)

    @override_settings(MAKE_WEBHOOK_URL="https://hook.example.com/abc")
    def test_reset_email_goes_through_make_when_webhook_is_set(self):
        with mock.patch("notifications.mail.deliver") as deliver:
            self.client.post(reverse("password_reset"), {"email": "nadia@example.com"})
        payload = deliver.call_args.args[0]
        self.assertEqual(payload["event"], "user.password_reset")
        self.assertEqual(payload["data"]["to"], "nadia@example.com")
        self.assertIn("https://lms.example.com/accounts/reset/", payload["data"]["text"])
        self.assertEqual(mail.outbox, [])


class MediaTests(TestCase):
    def test_uploaded_files_need_staff_sign_in(self):
        response = self.client.get("/media/knowledge/book.pdf")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
