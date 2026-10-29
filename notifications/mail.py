"""Email people: through Make when MAKE_WEBHOOK_URL is set, otherwise through Django's own email settings.

Every email sent through Make is an event with data.to, data.subject, data.text and data.html, so one Gmail module
in the scenario (filtered on "data.to exists") sends all of them.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape, linebreaks

from .make import build_payload, deliver


def site_url(path, request=None):
    """Absolute link for emails. SITE_URL wins, so links work even when the admin is used on localhost."""
    if settings.SITE_URL:
        return settings.SITE_URL + path
    if request is not None:
        return request.build_absolute_uri(path)
    return "http://127.0.0.1:8000" + path


def send_email(event, to, subject, text, html="", **extra):
    """Send one email. Raises on failure, so callers decide what a failed email means."""
    html = html or linebreaks(escape(text))
    if settings.MAKE_WEBHOOK_URL:
        deliver(build_payload(event, {"to": to, "subject": subject, "text": text, "html": html, **extra}))
        return
    message = EmailMultiAlternatives(subject=subject, body=text, to=[to])
    message.attach_alternative(html, "text/html")
    message.send()
