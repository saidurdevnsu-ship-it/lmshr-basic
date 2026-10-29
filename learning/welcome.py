"""Welcome email for new staff accounts, with a one-time link to set their own password."""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from notifications.mail import send_email, site_url

logger = logging.getLogger(__name__)


def send_welcome_email(user, request):
    """Email the user their username, roles and a set-password link. Returns True if sent.

    Never includes a password: the link lets them choose their own (valid for PASSWORD_RESET_TIMEOUT, 3 days).
    With MAKE_WEBHOOK_URL set, the email goes out through Make (a "user.welcome" event the scenario emails on);
    otherwise through Django's own email settings. Links use SITE_URL when it's set.
    """
    if not user.email:
        return False
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    context = {
        "user": user,
        "name": user.get_short_name() or user.get_username(),
        "roles": list(user.groups.values_list("name", flat=True)),
        "company_name": settings.HR_COMPANY_NAME,
        "login_url": site_url(reverse("login"), request),
        "set_password_url": site_url(reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token}), request),
        "link_days": settings.PASSWORD_RESET_TIMEOUT // 86400,
    }
    subject = f"Welcome to STS Pulse, {context['name']}"
    text = render_to_string("emails/welcome.txt", context)
    html = render_to_string("emails/welcome.html", context)
    try:
        send_email("user.welcome", user.email, subject, text, html,
                   name=context["name"], username=user.get_username(), roles=context["roles"],
                   set_password_url=context["set_password_url"], login_url=context["login_url"])
    except Exception:  # email or Make problems must not break creating the account
        logger.exception("Couldn't send the welcome email to %s", user.email)
        return False
    return True
