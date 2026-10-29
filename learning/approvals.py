"""One rule for every approval in the system: nobody approves or rejects their own work, not even the super admin.

Used by question approval, blueprint review and leave review, so the rule is the same everywhere.
"""

SELF_APPROVAL_MESSAGE = "You can't approve or reject your own work; someone else has to review it."


def is_own(user, author_id):
    """True if the user is the author of the thing being reviewed."""
    return author_id is not None and author_id == user.pk


def others_only(queryset, user, author_field):
    """The queryset without the user's own items, e.g. others_only(questions, user, "created_by")."""
    return queryset.exclude(**{author_field: user.pk})
