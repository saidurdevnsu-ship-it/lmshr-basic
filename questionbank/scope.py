"""Which subjects and grades a person may see and act on, from their subject assignments.

Super admins and exam controllers (who need every subject for final papers) see everything. Everyone else sees
only their assigned subjects; with no assignment, they see nothing.
"""

from django.db.models import Q

from .models import Subject, SubjectAssignment

FINAL_PERM = "questionbank.manage_final_papers"


def sees_all_subjects(user):
    return user.is_superuser or user.has_perm(FINAL_PERM)


def _assignments(user):
    return list(SubjectAssignment.objects.filter(user=user).values_list("subject_id", "grade_id"))


def subject_filter(user, prefix=""):
    """A Q matching rows in the user's assignments (None when they see everything). prefix reaches the subject and
    grade through a relation, e.g. "blueprint__"."""
    if sees_all_subjects(user):
        return None
    q = Q(pk__in=[])  # matches nothing
    for subject_id, grade_id in _assignments(user):
        if grade_id is None:
            q |= Q(**{f"{prefix}subject_id": subject_id})
        else:
            q |= Q(**{f"{prefix}subject_id": subject_id, f"{prefix}grade_id": grade_id})
    return q


def in_scope(queryset, user, prefix=""):
    q = subject_filter(user, prefix)
    return queryset if q is None else queryset.filter(q)


def allowed_subjects(user):
    subjects = Subject.objects.all()
    if sees_all_subjects(user):
        return subjects
    return subjects.filter(pk__in=[s for s, _ in _assignments(user)])


def covers(user, subject, grade):
    """Whether the user is assigned to this subject and grade."""
    if sees_all_subjects(user):
        return True
    return any(s == subject.pk and g in (None, grade.pk) for s, g in _assignments(user))


def has_no_assignments(user):
    return not sees_all_subjects(user) and not SubjectAssignment.objects.filter(user=user).exists()
