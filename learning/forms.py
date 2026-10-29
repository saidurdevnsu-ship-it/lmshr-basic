import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.template.loader import render_to_string

from notifications.mail import send_email

logger = logging.getLogger(__name__)


class ResetPasswordForm(PasswordResetForm):
    """"Forgot password" form whose email goes out like the welcome email: through Make when it's set up,
    with links on SITE_URL."""

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email,
                  html_email_template_name=None):
        if settings.SITE_URL:
            parts = urlsplit(settings.SITE_URL)
            context = {**context, "protocol": parts.scheme, "domain": parts.netloc}
        subject = "".join(render_to_string(subject_template_name, context).splitlines())
        text = render_to_string(email_template_name, context)
        html = render_to_string(html_email_template_name, context) if html_email_template_name else ""
        try:
            send_email("user.password_reset", to_email, subject, text, html)
        except Exception:
            logger.exception("Couldn't send the password reset email to %s", to_email)
