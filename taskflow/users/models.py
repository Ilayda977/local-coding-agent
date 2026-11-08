from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Role(str, Enum):
    """System-wide role. Project-level permissions live in ``projects``."""
    ADMIN = "admin"
    MEMBER = "member"


@dataclass
class User:
    id: str
    email: str
    name: str
    created_at: datetime
    handle: str = ""  # used for @mentions, always stored lower-case
    role: Role = Role.MEMBER
    active: bool = True
