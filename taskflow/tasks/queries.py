"""Filtering, sorting and pagination of task lists."""
import math
from dataclasses import dataclass
from datetime import date
from typing import Optional

from common.errors import ValidationError
from tasks.models import Priority, Status

MAX_PER_PAGE = 100


@dataclass
class TaskFilter:
    status: Optional[Status] = None
    assignee_id: Optional[str] = None
    min_priority: Optional[Priority] = None
    text: Optional[str] = None


def apply_filter(tasks, task_filter=None):
    if task_filter is None:
        return list(tasks)
    text = task_filter.text.lower() if task_filter.text else None
    result = []
    for task in tasks:
        if task_filter.status is not None and task.status != task_filter.status:
            continue
        if task_filter.assignee_id is not None and task.assignee_id != task_filter.assignee_id:
            continue
        if task_filter.min_priority is not None and task.priority < task_filter.min_priority:
            continue
        if text and text not in task.title.lower() and text not in task.description.lower():
            continue
        result.append(task)
    return result


SORT_KEYS = {
    # Most important first; older tasks first among equal priorities.
    "priority": lambda task: (-task.priority, task.created_at),
    # Tasks without a due date go last.
    "due_date": lambda task: (task.due_date is None, task.due_date or date.max, -task.priority),
    "created": lambda task: task.created_at,
}


def sort_tasks(tasks, by="priority"):
    if by not in SORT_KEYS:
        raise ValidationError(f"unknown sort key: {by}")
    return sorted(tasks, key=SORT_KEYS[by])


@dataclass
class Page:
    items: list
    page: int
    per_page: int
    total: int

    @property
    def pages(self):
        return max(1, math.ceil(self.total / self.per_page))


def paginate(items, page=1, per_page=20):
    """Return the 1-based ``page`` of ``items``."""
    if page < 1:
        raise ValidationError("page must be >= 1")
    if not 1 <= per_page <= MAX_PER_PAGE:
        raise ValidationError(f"per_page must be between 1 and {MAX_PER_PAGE}")
    items = list(items)
    start = (page - 1) * per_page
    return Page(items=items[start:start + per_page], page=page,
                per_page=per_page, total=len(items))
