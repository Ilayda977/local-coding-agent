"""Project lifecycle and membership."""
import events
from common.errors import ConflictError, ValidationError
from common.validation import require_text
from projects import permissions
from projects.models import Project, ProjectRole


class ProjectService:
    def __init__(self, repository, users, ids, clock, bus):
        self._projects = repository
        self._users = users
        self._ids = ids
        self._clock = clock
        self._bus = bus

    def create(self, owner_id, name):
        self._users.require_active(owner_id)
        project = Project(
            id=self._ids.next(),
            name=require_text(name, "project name", max_length=120),
            owner_id=owner_id,
            created_at=self._clock.now(),
            members={owner_id: ProjectRole.OWNER},
        )
        return self._projects.add(project)

    def get(self, project_id):
        return self._projects.get(project_id)

    def get_for_user(self, project_id, user_id):
        project = self._projects.get(project_id)
        permissions.require(permissions.can_view(project, user_id),
                            f"user {user_id} cannot view project {project_id}")
        return project

    def add_member(self, project_id, actor_id, user_id, role=ProjectRole.EDITOR):
        project = self._projects.get(project_id)
        permissions.require(permissions.can_manage(project, actor_id),
                            "only the project owner can add members")
        role = ProjectRole(role)
        if role == ProjectRole.OWNER:
            raise ValidationError("a project has exactly one owner")
        self._users.require_active(user_id)
        if user_id in project.members:
            raise ConflictError(f"user {user_id} is already a member")
        project.members[user_id] = role
        self._projects.update(project)
        self._bus.publish(events.PROJECT_MEMBER_ADDED, project_id=project.id,
                          user_id=user_id, actor_id=actor_id)
        return project

    def remove_member(self, project_id, actor_id, user_id):
        project = self._projects.get(project_id)
        permissions.require(permissions.can_manage(project, actor_id),
                            "only the project owner can remove members")
        if user_id == project.owner_id:
            raise ValidationError("the owner cannot be removed from the project")
        if user_id not in project.members:
            raise ValidationError(f"user {user_id} is not a member")
        del project.members[user_id]
        return self._projects.update(project)

    def archive(self, project_id, actor_id):
        project = self._projects.get(project_id)
        permissions.require(permissions.can_manage(project, actor_id),
                            "only the project owner can archive the project")
        project.archived = True
        return self._projects.update(project)

    def list_for_user(self, user_id, include_archived=False):
        return self._projects.list(
            lambda project: permissions.can_view(project, user_id)
            and (include_archived or not project.archived)
        )
