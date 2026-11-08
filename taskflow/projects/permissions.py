"""Project-level permission rules.

* viewers can read and comment,
* editors can create and change tasks,
* owners can additionally manage members and archive the project,
* an archived project is read-only for everyone (no tasks, no comments).
"""
from common.errors import PermissionDeniedError
from projects.models import ProjectRole

EDIT_ROLES = {ProjectRole.OWNER, ProjectRole.EDITOR}


def role_of(project, user_id):
    return project.members.get(user_id)


def can_view(project, user_id):
    return role_of(project, user_id) is not None


def can_comment(project, user_id):
    return not project.archived and can_view(project, user_id)


def can_edit(project, user_id):
    return not project.archived and role_of(project, user_id) in EDIT_ROLES


def can_manage(project, user_id):
    return not project.archived and role_of(project, user_id) == ProjectRole.OWNER


def require(allowed, message):
    if not allowed:
        raise PermissionDeniedError(message)
