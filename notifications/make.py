"""Send app events to a Make.com scenario, by webhook (preferred) or mailhook.

Each event is JSON: {"event": "...", "app": "STS Pulse", "sent_at": "...", "data": {...}}, so one scenario can route
on "event". Never send passwords, leave reasons or exam content here: the data leaves this system. The one exception
is "user.welcome" (learning/welcome.py), which carries the one-time set-password link so Make can email it.
"""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def make_configured():
    return bool(settings.MAKE_WEBHOOK_URL or settings.MAKE_MAILHOOK_ADDRESS)


def build_payload(event, data):
    return {"event": event, "app": "STS Pulse", "sent_at": timezone.localtime().isoformat(), "data": data}


def deliver(payload):
    """Send one payload now. Returns "webhook", "mailhook" or None (not configured). Raises on failure."""
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if settings.MAKE_WEBHOOK_URL:
        request = urllib.request.Request(
            settings.MAKE_WEBHOOK_URL, data=body.encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        return "webhook"
    if settings.MAKE_MAILHOOK_ADDRESS:
        EmailMessage(subject=f"[STS Pulse] {payload['event']}", body=body,
                     to=[settings.MAKE_MAILHOOK_ADDRESS]).send()
        return "mailhook"
    return None


def send_event(event, data):
    """Queue an event for Make once the current database transaction commits. Failures are logged, never raised."""
    if not make_configured():
        return
    payload = build_payload(event, data)

    def _send():
        try:
            deliver(payload)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning("Couldn't send %s to Make: %s", event, exc)
        except Exception:
            logger.exception("Couldn't send %s to Make", event)

    transaction.on_commit(_send)


# ---------- Event shapes ----------

def user_created_data(user, created_by=None):
    return {
        "username": user.get_username(),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.get_full_name() or user.get_username(),
        "email": user.email,
        "roles": list(user.groups.values_list("name", flat=True)),
        "created_by": created_by.get_username() if created_by else "",
        "created_at": timezone.localtime(user.date_joined).isoformat(),
    }


def leave_approved_data(leave):
    employee = leave.employee
    return {
        "employee_id": employee.employee_id,
        "name": employee.full_name,
        "email": employee.user.email,
        "phone": employee.phone,
        "department": str(employee.department),
        "designation": str(employee.designation),
        "leave_type": str(leave.leave_type),
        "start_date": leave.start_date.isoformat(),
        "end_date": leave.end_date.isoformat(),
        "working_days": float(leave.days),
        "approved_by": leave.reviewed_by.get_full_name() or leave.reviewed_by.get_username() if leave.reviewed_by else "",
        "approved_at": timezone.localtime(leave.reviewed_at).isoformat() if leave.reviewed_at else "",
    }
