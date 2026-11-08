"""Turns domain events into user notifications."""
import events
from notifications import models
from tasks.models import Status


class NotificationDispatcher:
    def __init__(self, bus, notifications, tasks, projects, users):
        self._notifications = notifications
        self._tasks = tasks
        self._projects = projects
        self._users = users
        bus.subscribe(events.TASK_ASSIGNED, self.on_task_assigned)
        bus.subscribe(events.TASK_STATUS_CHANGED, self.on_task_status_changed)
        bus.subscribe(events.PROJECT_MEMBER_ADDED, self.on_member_added)
        bus.subscribe(events.COMMENT_ADDED, self.on_comment_added)

    def _deliver(self, user_id, kind, message):
        """Single exit point: deactivated accounts never receive anything."""
        if not self._users.get(user_id).active:
            return None
        return self._notifications.notify(user_id, kind, message)

    def on_task_assigned(self, task_id, assignee_id, actor_id):
        if assignee_id is None or assignee_id == actor_id:
            return  # nobody needs to be told about their own action
        task = self._tasks.get(task_id)
        self._deliver(assignee_id, models.TASK_ASSIGNED, f"You were assigned '{task.title}'")

    def on_task_status_changed(self, task_id, old_status, new_status, actor_id):
        if new_status != Status.DONE:
            return
        task = self._tasks.get(task_id)
        if task.created_by != actor_id:
            self._deliver(task.created_by, models.TASK_COMPLETED, f"'{task.title}' was completed")

    def on_member_added(self, project_id, user_id, actor_id):
        project = self._projects.get(project_id)
        self._deliver(user_id, models.PROJECT_INVITE, f"You were added to project '{project.name}'")

    def on_comment_added(self, comment_id, task_id, author_id, mentioned_ids):
        task = self._tasks.get(task_id)
        for user_id in mentioned_ids:
            self._deliver(user_id, models.MENTIONED, f"You were mentioned on '{task.title}'")
        # The assignee hears about new comments, but only once: a mention is enough.
        assignee = task.assignee_id
        if assignee and assignee != author_id and assignee not in mentioned_ids:
            self._deliver(assignee, models.TASK_COMMENTED, f"New comment on '{task.title}'")
