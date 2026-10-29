from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from notifications.make import build_payload, deliver

SAMPLES = {
    "user.created": {
        "username": "sample.teacher", "first_name": "Sample", "last_name": "Teacher",
        "full_name": "Sample Teacher", "email": "sample.teacher@example.com",
        "roles": ["Teacher / Subject Expert"], "created_by": "superadmin", "created_at": "2026-10-28T10:00:00+06:00",
    },
    "user.welcome": {
        "to": "sample.teacher@example.com", "subject": "Welcome to STS Pulse, Sample",
        "text": "Hi Sample,\n\nWelcome to STS Pulse...", "html": "<p>Hi Sample,</p><p>Welcome to STS Pulse...</p>",
        "name": "Sample", "username": "sample.teacher", "roles": ["Teacher / Subject Expert"],
        "set_password_url": "http://127.0.0.1:8000/accounts/reset/sample/set-password/",
        "login_url": "http://127.0.0.1:8000/accounts/login/",
    },
    "user.password_reset": {
        "to": "sample.teacher@example.com", "subject": "Password reset on 127.0.0.1:8000",
        "text": "You're receiving this email because you requested a password reset...",
        "html": "<p>You're receiving this email because you requested a password reset...</p>",
    },
    "leave.approved": {
        "employee_id": "T-000", "name": "Sample Teacher", "email": "sample.teacher@example.com",
        "department": "Academics", "designation": "Teacher",
        "leave_type": "Casual", "start_date": "2026-11-01", "end_date": "2026-11-03", "working_days": 3.0,
        "approved_by": "HR Manager", "approved_at": "2026-10-28T10:05:00+06:00",
    },
}


class Command(BaseCommand):
    help = "Send one sample of each event to Make so the scenario can learn the data structure. Uses fake data."

    def add_arguments(self, parser):
        parser.add_argument("events", nargs="*", help=f"Which events: {', '.join(SAMPLES)} (default: all).")

    def handle(self, *args, events, **options):
        if not (settings.MAKE_WEBHOOK_URL or settings.MAKE_MAILHOOK_ADDRESS):
            raise CommandError("Set MAKE_WEBHOOK_URL (or MAKE_MAILHOOK_ADDRESS) in .env first.")
        unknown = set(events) - set(SAMPLES)
        if unknown:
            raise CommandError(f"Unknown event(s): {', '.join(sorted(unknown))}. Choose from: {', '.join(SAMPLES)}.")
        for event in events or SAMPLES:
            try:
                via = deliver(build_payload(event, SAMPLES[event]))
            except Exception as exc:
                raise CommandError(f"Sending {event} failed: {exc}")
            note = "" if via == "webhook" or "smtp" in settings.MAILERS["default"]["BACKEND"] else \
                " (printed above only: set EMAIL_HOST in .env so it actually reaches the mailhook)"
            self.stdout.write(self.style.SUCCESS(f"Sent sample {event} via {via}{note}"))
