"""Readable, deterministic identifiers such as ``user-1`` or ``task-12``."""
import itertools


class IdGenerator:
    def __init__(self, prefix):
        self._prefix = prefix
        self._counter = itertools.count(1)

    def next(self):
        return f"{self._prefix}-{next(self._counter)}"
