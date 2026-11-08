"""Synchronous publish/subscribe bus that decouples modules.

Services publish events; the notification dispatcher, the activity log and
the task service (for membership changes) subscribe to them.
"""
from collections import defaultdict

TASK_ASSIGNED = "task.assigned"
TASK_STATUS_CHANGED = "task.status_changed"
PROJECT_MEMBER_ADDED = "project.member_added"
PROJECT_MEMBER_REMOVED = "project.member_removed"
COMMENT_ADDED = "comment.added"


class EventBus:
    def __init__(self):
        self._handlers = defaultdict(list)
        self.published = []

    def subscribe(self, name, handler):
        self._handlers[name].append(handler)

    def publish(self, name, **payload):
        """Call every handler of ``name`` in subscription order."""
        self.published.append((name, payload))
        for handler in self._handlers[name]:
            handler(**payload)
