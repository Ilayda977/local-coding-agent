"""Allowed task status transitions.

    TODO ──► IN_PROGRESS ──► IN_REVIEW ──► DONE
      │  ▲       │  ▲            │
      ▼  │       ▼  │            ▼
      BLOCKED ◄──┘  └──── (changes requested)

A DONE task can only come back through ``TaskService.reopen``.
"""
from common.errors import ValidationError
from tasks.models import Status

ALLOWED_TRANSITIONS = {
    Status.TODO: {Status.IN_PROGRESS, Status.BLOCKED},
    Status.IN_PROGRESS: {Status.TODO, Status.BLOCKED, Status.IN_REVIEW},
    Status.BLOCKED: {Status.TODO, Status.IN_PROGRESS},
    Status.IN_REVIEW: {Status.IN_PROGRESS, Status.DONE},
    Status.DONE: set(),
}


def can_transition(current, target):
    return Status(target) in ALLOWED_TRANSITIONS[Status(current)]


def ensure_transition(current, target):
    current, target = Status(current), Status(target)
    if current == target:
        raise ValidationError(f"task is already {current.value}")
    if not can_transition(current, target):
        raise ValidationError(f"cannot move task from {current.value} to {target.value}")
