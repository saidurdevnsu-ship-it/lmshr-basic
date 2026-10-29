"""The predefined roles and their default permissions.

Roles are created with these defaults when missing (after every migrate, and by setup_academics / setup_hr). After
that they belong to the school: super admins edit them under Roles, and nothing overwrites those edits unless someone
asks for a reset (the "Reset to default permissions" action, or a setup command with --reset).
"""

from django.contrib.auth.models import Group, Permission
from django.db.models import Q

FINAL_PAPERS = "questionbank.manage_final_papers"
EXAM_CONTROLLER = "Exam Controller"

# Each role: a description and its permissions as "app.codename", or "app.*" for every permission of an app.
# "-app.codename" removes one again (applied after the others).
DEFAULT_ROLES = {
    "Teacher / Subject Expert": {
        "description": "Uploads materials, writes questions and blueprints for their assigned subjects.",
        "permissions": [
            "questionbank.view_subject", "questionbank.view_grade", "questionbank.view_academicevent",
            "questionbank.add_knowledgesource", "questionbank.change_knowledgesource",
            "questionbank.delete_knowledgesource", "questionbank.view_knowledgesource",
            "questionbank.add_question", "questionbank.change_question", "questionbank.view_question",
            "questionbank.add_questionblueprint", "questionbank.change_questionblueprint",
            "questionbank.view_questionblueprint",
            "questionbank.add_blueprintitem", "questionbank.change_blueprintitem",
            "questionbank.delete_blueprintitem", "questionbank.view_blueprintitem",
        ],
    },
    "Head of Department": {
        "description": "Reviews blueprints and approves questions for their assigned subjects.",
        "permissions": ["questionbank.*", f"-{FINAL_PAPERS}",
                        "-questionbank.add_subjectassignment", "-questionbank.change_subjectassignment",
                        "-questionbank.delete_subjectassignment"],
    },
    EXAM_CONTROLLER: {
        "description": "Generates, sees and locks the confidential final papers; manages the academic calendar.",
        "permissions": [
            FINAL_PAPERS, "questionbank.view_subject", "questionbank.view_grade",
            "questionbank.view_knowledgesource", "questionbank.view_academicevent",
            "questionbank.add_academicevent", "questionbank.change_academicevent",
            "questionbank.delete_academicevent", "questionbank.view_questionblueprint",
            "questionbank.view_blueprintitem",
        ],
    },
    "Read-Only": {
        "description": "Views materials, the question bank and the calendar for their assigned subjects.",
        "permissions": ["questionbank.view_subject", "questionbank.view_grade", "questionbank.view_knowledgesource",
                        "questionbank.view_academicevent", "questionbank.view_question"],
    },
    "HR Manager": {
        "description": "Manages employees, attendance, leave and HR reports; can view user accounts.",
        # View-only on accounts: changing users is for super admins (see learning/admin.py).
        "permissions": ["hr.*", "auth.view_user", "auth.view_group"],
    },
    "Employee": {
        "description": "Self-service: own profile, attendance and leave requests.",
        "permissions": ["hr.view_employee", "hr.view_attendance", "hr.view_holiday", "hr.view_leavetype",
                        "hr.add_leaverequest", "hr.view_leaverequest"],
    },
}


def default_permissions(name):
    """The default Permission queryset for a predefined role."""
    include, exclude = Q(pk__in=[]), Q(pk__in=[])
    for entry in DEFAULT_ROLES[name]["permissions"]:
        target = entry.lstrip("-")
        app, codename = target.split(".")
        q = Q(content_type__app_label=app) if codename == "*" else Q(content_type__app_label=app, codename=codename)
        if entry.startswith("-"):
            exclude |= q
        else:
            include |= q
    return Permission.objects.filter(include).exclude(exclude)


def keep_final_papers_confidential(log=None):
    """Only the Exam Controller role may hold the final paper permission; take it off any other role."""
    app, codename = FINAL_PAPERS.split(".")
    final = Permission.objects.filter(content_type__app_label=app, codename=codename).first()
    if final is None:
        return []
    removed = []
    for group in Group.objects.exclude(name=EXAM_CONTROLLER).filter(permissions=final):
        group.permissions.remove(final)
        removed.append(group.name)
        if log:
            log(f"Removed final-paper access from role: {group.name}")
    return removed


def ensure_roles(names=None, reset=False, log=None):
    """Create missing predefined roles with their defaults; with reset, also restore existing ones.
    Returns {name: "created" | "reset" | "kept"}."""
    result = {}
    for name in names or DEFAULT_ROLES:
        group, created = Group.objects.get_or_create(name=name)
        if created or reset:
            group.permissions.set(default_permissions(name))
            result[name] = "created" if created else "reset"
        else:
            result[name] = "kept"
        if log:
            status = {"created": "created with default permissions", "reset": "reset to default permissions",
                      "kept": "already exists, kept as edited (use --reset to restore defaults)"}[result[name]]
            log(f"Role {name}: {status}")
    keep_final_papers_confidential(log)
    return result


def create_missing_roles(sender, **kwargs):
    """post_migrate: make sure every permission exists, then add any predefined role that's missing."""
    from django.apps import apps
    from django.contrib.auth.management import create_permissions

    for app_config in apps.get_app_configs():
        create_permissions(app_config, verbosity=0, using=kwargs.get("using", "default"))
    ensure_roles()
