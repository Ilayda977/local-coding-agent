"""In-app notifications with an email outbox."""
from common.errors import PermissionDeniedError
from notifications.models import Notification
from notifications.preferences import in_quiet_hours


class NotificationService:
    def __init__(self, repository, preferences, ids, clock):
        self._notifications = repository
        self._preferences = preferences
        self._ids = ids
        self._clock = clock
        self.email_outbox = []  # (user_id, message) pairs waiting to be sent

    def notify(self, user_id, kind, message):
        """Create an in-app notification unless the user muted ``kind``.

        Returns the notification, or ``None`` when it was muted.
        """
        prefs = self._preferences.get(user_id)
        if kind in prefs.muted_kinds:
            return None
        now = self._clock.now()
        notification = Notification(id=self._ids.next(), user_id=user_id, kind=kind,
                                    message=message, created_at=now)
        self._notifications.add(notification)
        if prefs.email_enabled and not in_quiet_hours(prefs, now.hour):
            self.email_outbox.append((user_id, message))
        return notification

    def for_user(self, user_id):
        """All notifications of a user, newest first."""
        items = self._notifications.list(lambda n: n.user_id == user_id)
        return sorted(items, key=lambda n: n.created_at, reverse=True)

    def unread(self, user_id):
        return [n for n in self.for_user(user_id) if not n.read]

    def unread_count(self, user_id):
        return len(self.unread(user_id))

    def mark_read(self, notification_id, user_id):
        notification = self._notifications.get(notification_id)
        if notification.user_id != user_id:
            raise PermissionDeniedError("cannot read another user's notification")
        notification.read = True
        return self._notifications.update(notification)

    def mark_all_read(self, user_id):
        for notification in self.unread(user_id):
            notification.read = True
            self._notifications.update(notification)
