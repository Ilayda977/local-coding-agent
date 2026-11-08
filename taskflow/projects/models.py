from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ProjectRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass
class Project:
    id: str
    name: str
    owner_id: str
    created_at: datetime
    members: dict = field(default_factory=dict)  # user_id -> ProjectRole
    archived: bool = False
