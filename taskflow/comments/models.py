from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Comment:
    id: str
    task_id: str
    author_id: str
    body: str
    created_at: datetime
    mentioned_ids: list = field(default_factory=list)  # users notified via @handle
    edited_at: Optional[datetime] = None
