"""Task creation, assignment, status changes and listing."""
import events
from common.errors import ValidationError
from common.validation import require_text
from projects import permissions
from tasks import queries, workflow
from tasks.models import Priority, Status, Task


class TaskService:
    def __init__(self, repository, projects, users, ids, clock, bus):
        self._tasks = repository
        self._projects = projects
        self._users = users
        self._ids = ids
        self._clock = clock
        self._bus = bus
        bus.subscribe(events.PROJECT_MEMBER_REMOVED, self.on_member_removed)

    # -- helpers -----------------------------------------------------------
    def _editable_project(self, project_id, actor_id):
        project = self._projects.get(project_id)
        permissions.require(permissions.can_edit(project, actor_id),
                            f"user {actor_id} cannot edit project {project_id}")
        return project

    def _check_assignee(self, project, assignee_id):
        self._users.require_active(assignee_id)
        if not permissions.can_view(project, assignee_id):
            raise ValidationError(f"user {assignee_id} is not a member of {project.id}")

    def _touch(self, task):
        task.updated_at = self._clock.now()
        return self._tasks.update(task)

    # -- commands ----------------------------------------------------------
    def create(self, project_id, actor_id, title, priority=Priority.MEDIUM,
               due_date=None, description="", assignee_id=None):
        project = self._editable_project(project_id, actor_id)
        if assignee_id is not None:
            self._check_assignee(project, assignee_id)
        now = self._clock.now()
        task = Task(
            id=self._ids.next(), project_id=project.id,
            title=require_text(title, "title", max_length=200),
            description=(description or "").strip(),
            created_by=actor_id, created_at=now, updated_at=now,
            priority=Priority(priority), assignee_id=assignee_id, due_date=due_date,
        )
        self._tasks.add(task)
        if assignee_id is not None:
            self._bus.publish(events.TASK_ASSIGNED, task_id=task.id,
                              assignee_id=assignee_id, actor_id=actor_id)
        return task

    def get(self, task_id):
        return self._tasks.get(task_id)

    def list_for_project(self, project_id, user_id):
        self._projects.get_for_user(project_id, user_id)
        return self._tasks.list(lambda t: t.project_id == project_id)

    def assign(self, task_id, actor_id, assignee_id):
        task = self._tasks.get(task_id)
        project = self._editable_project(task.project_id, actor_id)
        self._check_assignee(project, assignee_id)
        task.assignee_id = assignee_id
        self._touch(task)
        self._bus.publish(events.TASK_ASSIGNED, task_id=task.id,
                          assignee_id=task.assignee_id, actor_id=actor_id)
        return task

    def on_member_removed(self, project_id, user_id, actor_id):
        """Someone left the project: their open tasks there become unassigned."""
        for task in self._tasks.list(lambda t: t.project_id == project_id):
            if task.assignee_id == user_id:
                task.assignee_id = None
                self._touch(task)

    def change_status(self, task_id, actor_id, status):
        task = self._tasks.get(task_id)
        self._editable_project(task.project_id, actor_id)
        status = Status(status)
        workflow.ensure_transition(task.status, status)
        old_status = task.status
        task.status = status
        if status == Status.DONE:
            task.completed_at = self._clock.now()
        self._touch(task)
        self._bus.publish(events.TASK_STATUS_CHANGED, task_id=task.id,
                          old_status=old_status, new_status=status, actor_id=actor_id)
        return task

    def reopen(self, task_id, actor_id):
        task = self._tasks.get(task_id)
        self._editable_project(task.project_id, actor_id)
        if task.status != Status.DONE:
            raise ValidationError("only done tasks can be reopened")
        old_status = task.status
        task.status = Status.TODO
        task.completed_at = None
        self._touch(task)
        self._bus.publish(events.TASK_STATUS_CHANGED, task_id=task.id,
                          old_status=old_status, new_status=task.status, actor_id=actor_id)
        return task

    # -- queries -----------------------------------------------------------
    def is_overdue(self, task, today=None):
        """A task is overdue when its due date has passed and it is not done."""
        today = today or self._clock.now().date()
        return (task.due_date is not None
                and task.status != Status.DONE
                and task.due_date < today)

    def overdue_tasks(self, project_id, user_id):
        self._projects.get_for_user(project_id, user_id)
        return [task for task in self._tasks.list(lambda t: t.project_id == project_id)
                if self.is_overdue(task)]

    def search(self, project_id, user_id, task_filter=None, sort_by="priority",
               page=1, per_page=20):
        self._projects.get_for_user(project_id, user_id)
        tasks = self._tasks.list(lambda t: t.project_id == project_id)
        tasks = queries.apply_filter(tasks, task_filter)
        tasks = queries.sort_tasks(tasks, by=sort_by)
        return queries.paginate(tasks, page=page, per_page=per_page)
