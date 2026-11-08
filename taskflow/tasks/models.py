from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, IntEnum
from typing import Optional


class Status(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    DONE = "done"


# Work that still needs attention. Used by reports (e.g. workload).
OPEN_STATUSES = frozenset({Status.TODO, Status.IN_PROGRESS, Status.BLOCKED, Status.IN_REVIEW})


class Priority(IntEnum):
    """Higher number means more important."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


@dataclass
class Task:
    id: str
    project_id: str
    title: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    description: str = ""
    status: Status = Status.TODO
    priority: Priority = Priority.MEDIUM
    assignee_id: Optional[str] = None
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None
