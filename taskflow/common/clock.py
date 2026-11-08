"""Clock abstraction so that time-dependent logic can be tested."""
from datetime import datetime, timedelta, timezone


class SystemClock:
    def now(self):
        return datetime.now(timezone.utc)


class FixedClock:
    """A clock that only moves when the test tells it to."""

    def __init__(self, current):
        self.current = current

    def now(self):
        return self.current

    def advance(self, **delta):
        self.current += timedelta(**delta)
        return self.current
