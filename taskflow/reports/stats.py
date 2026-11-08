"""Read-only project reports built on top of the task service."""
from collections import Counter
from dataclasses import dataclass

from tasks.models import OPEN_STATUSES, Status


@dataclass
class Progress:
    total: int
    by_status: dict
    done: int

    @property
    def percent_done(self):
        """Whole-number percentage of tasks that are done (0 for an empty project)."""
        if self.total == 0:
            return 0
        return round(self.done * 100 / self.total)


class ProjectReports:
    def __init__(self, tasks):
        self._tasks = tasks

    def progress(self, project_id, user_id):
        tasks = self._tasks.list_for_project(project_id, user_id)
        by_status = Counter(task.status.value for task in tasks)
        # A task counts as done while it has a completion time; reopen() clears it.
        done = sum(1 for task in tasks if task.completed_at is not None)
        return Progress(total=len(tasks), by_status=dict(by_status), done=done)

    def workload(self, project_id, user_id):
        """Open (not done) tasks per assignee: {user_id: count}."""
        tasks = self._tasks.list_for_project(project_id, user_id)
        counts = Counter(task.assignee_id for task in tasks
                         if task.assignee_id and task.status in OPEN_STATUSES)
        return dict(counts)

    def blocked_tasks(self, project_id, user_id):
        tasks = self._tasks.list_for_project(project_id, user_id)
        return [task for task in tasks if task.status == Status.BLOCKED]
