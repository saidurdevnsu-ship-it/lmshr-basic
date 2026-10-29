"""Record key activities in the audit log. Call record() where something important happens."""

import logging

from .models import AuditEvent

logger = logging.getLogger(__name__)
Action = AuditEvent.Action


def record(actor, action, target=None, *, details="", request=None, target_type="", target_id="", target_repr=""):
    """Add one audit entry. Never raises: a logging problem must not stop the action itself.

    Pass a model instance as target, or target_type / target_id / target_repr for records already gone.
    Keep details free of passwords and final paper questions.
    """
    try:
        if target is not None:
            target_type = target_type or target._meta.verbose_name
            target_id = target_id or str(target.pk)
            target_repr = target_repr or str(target)
        actor = actor if getattr(actor, "is_authenticated", False) else None
        AuditEvent.objects.create(
            actor=actor,
            actor_name=actor.get_username() if actor else "",
            action=action,
            target_type=str(target_type)[:100],
            target_id=str(target_id)[:50],
            target=str(target_repr)[:200],
            details=details,
            ip_address=request.META.get("REMOTE_ADDR") if request is not None else None,
        )
    except Exception:
        logger.exception("Couldn't write audit entry %s", action)
