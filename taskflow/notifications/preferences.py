"""Per-user notification preferences."""
from dataclasses import dataclass, field
from typing import Optional, Tuple

from common.errors import ValidationError


@dataclass
class Preferences:
    muted_kinds: set = field(default_factory=set)
    email_enabled: bool = False
    # (start_hour, end_hour) in UTC; may wrap past midnight, e.g. (22, 7).
    quiet_hours: Optional[Tuple[int, int]] = None


def in_quiet_hours(preferences, hour):
    if preferences.quiet_hours is None:
        return False
    start, end = preferences.quiet_hours
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


class PreferenceStore:
    def __init__(self):
        self._preferences = {}

    def get(self, user_id):
        return self._preferences.setdefault(user_id, Preferences())

    def mute(self, user_id, kind):
        self.get(user_id).muted_kinds.add(kind)

    def unmute(self, user_id, kind):
        self.get(user_id).muted_kinds.discard(kind)

    def set_email(self, user_id, enabled):
        self.get(user_id).email_enabled = bool(enabled)

    def set_quiet_hours(self, user_id, start, end):
        for hour in (start, end):
            if not 0 <= hour <= 23:
                raise ValidationError("quiet hours must be between 0 and 23")
        self.get(user_id).quiet_hours = (start, end)
