"""In-memory repository used by every service.

Entities are plain dataclasses with an ``id`` attribute.
"""
from common.errors import ConflictError, NotFoundError


class InMemoryRepository:
    def __init__(self, entity_name):
        self._entity_name = entity_name
        self._items = {}

    def add(self, item):
        if item.id in self._items:
            raise ConflictError(f"{self._entity_name} {item.id} already exists")
        self._items[item.id] = item
        return item

    def get(self, item_id):
        try:
            return self._items[item_id]
        except KeyError:
            raise NotFoundError(f"{self._entity_name} {item_id} not found") from None

    def find(self, item_id):
        return self._items.get(item_id)

    def list(self, predicate=None):
        """Return items in insertion order, optionally filtered."""
        return [item for item in self._items.values() if predicate is None or predicate(item)]

    def update(self, item):
        self.get(item.id)
        self._items[item.id] = item
        return item

    def remove(self, item_id):
        self.get(item_id)
        del self._items[item_id]

    def __len__(self):
        return len(self._items)
