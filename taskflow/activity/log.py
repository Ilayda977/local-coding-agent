"""An audit trail: who did what, when. Built only from published events."""
from dataclasses import dataclass
from datetime import datetime

import events


@dataclass
class ActivityEntry:
    at: datetime
    kind: str
    actor_id: str
    subject_id: str  # task or project the entry is about
    detail: str


class ActivityLog:
    def __init__(self, bus, clock):
        self._clock = clock
        self.entries = []
        bus.subscribe(events.TASK_STATUS_CHANGED, self._on_status_changed)
        bus.subscribe(events.TASK_ASSIGNED, self._on_assigned)
        bus.subscribe(events.PROJECT_MEMBER_ADDED, self._on_member_added)
        bus.subscribe(events.PROJECT_MEMBER_REMOVED, self._on_member_removed)
        bus.subscribe(events.COMMENT_ADDED, self._on_comment_added)

    def _record(self, kind, actor_id, subject_id, detail):
        self.entries.append(ActivityEntry(self._clock.now(), kind, actor_id, subject_id, detail))

    def _on_status_changed(self, task_id, old_status, new_status, actor_id):
        self._record("status", actor_id, task_id, f"{old_status.value} -> {new_status.value}")

    def _on_assigned(self, task_id, assignee_id, actor_id):
        self._record("assigned", actor_id, task_id, f"assigned to {assignee_id}")

    def _on_member_added(self, project_id, user_id, actor_id):
        self._record("member_added", actor_id, project_id, f"added {user_id}")

    def _on_member_removed(self, project_id, user_id, actor_id):
        self._record("member_removed", actor_id, project_id, f"removed {user_id}")

    def _on_comment_added(self, comment_id, task_id, author_id, mentioned_ids):
        self._record("comment", author_id, task_id, f"comment {comment_id}")

    def for_subject(self, subject_id):
        return [entry for entry in self.entries if entry.subject_id == subject_id]

    def recent(self, limit=20):
        return list(reversed(self.entries))[:limit]
