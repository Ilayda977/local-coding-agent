"""Turns domain events into user notifications."""
import events
from notifications import models
from tasks.models import Status


class NotificationDispatcher:
    def __init__(self, bus, notifications, tasks, projects):
        self._notifications = notifications
        self._tasks = tasks
        self._projects = projects
        bus.subscribe(events.TASK_ASSIGNED, self.on_task_assigned)
        bus.subscribe(events.TASK_STATUS_CHANGED, self.on_task_status_changed)
        bus.subscribe(events.PROJECT_MEMBER_ADDED, self.on_member_added)

    def on_task_assigned(self, task_id, assignee_id, actor_id):
        if assignee_id == actor_id:
            return  # nobody needs to be told about their own action
        task = self._tasks.get(task_id)
        self._notifications.notify(assignee_id, models.TASK_ASSIGNED,
                                   f"You were assigned '{task.title}'")

    def on_task_status_changed(self, task_id, old_status, new_status, actor_id):
        if new_status != Status.DONE:
            return
        task = self._tasks.get(task_id)
        if task.created_by != actor_id:
            self._notifications.notify(task.created_by, models.TASK_COMPLETED,
                                       f"'{task.title}' was completed")

    def on_member_added(self, project_id, user_id, actor_id):
        project = self._projects.get(project_id)
        self._notifications.notify(user_id, models.PROJECT_INVITE,
                                   f"You were added to project '{project.name}'")
