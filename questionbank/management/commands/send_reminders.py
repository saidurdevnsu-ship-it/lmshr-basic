import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from notifications.mail import send_email, site_url
from questionbank.reminders import ensure_reminders

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = ("Create today's deadline reminders for every staff member and email the new ones. "
            "Run it once a day (Task Scheduler or cron), e.g. at 8 AM.")

    def handle(self, *args, **options):
        emailed = 0
        for user in get_user_model().objects.filter(is_active=True, is_staff=True):
            new = ensure_reminders(user)
            if not new or not user.email:
                continue
            lines = [f"Hi {user.get_short_name() or user.get_username()},", "",
                     "These deadlines need your attention:", ""]
            for n in new:
                lines += [f"• {n.title}", f"  {site_url(n.url)}" if n.url else "", ""]
            subject = new[0].title if len(new) == 1 else f"{len(new)} deadline reminders"
            try:
                send_email("reminder.digest", user.email, subject, "\n".join(lines))
            except Exception:
                logger.exception("Couldn't email reminders to %s", user.email)
                self.stderr.write(f"Couldn't email {user.email}")
            else:
                emailed += 1
        self.stdout.write(self.style.SUCCESS(f"Emailed reminders to {emailed} user(s)."))
