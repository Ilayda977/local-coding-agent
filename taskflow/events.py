"""Synchronous publish/subscribe bus that decouples modules.

Services publish events; the notification dispatcher subscribes to them.
"""
from collections import defaultdict

TASK_ASSIGNED = "task.assigned"
TASK_STATUS_CHANGED = "task.status_changed"
PROJECT_MEMBER_ADDED = "project.member_added"


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
