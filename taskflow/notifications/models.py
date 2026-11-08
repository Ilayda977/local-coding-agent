from dataclasses import dataclass
from datetime import datetime

TASK_ASSIGNED = "task_assigned"
TASK_COMPLETED = "task_completed"
TASK_COMMENTED = "task_commented"
MENTIONED = "mentioned"
PROJECT_INVITE = "project_invite"


@dataclass
class Notification:
    id: str
    user_id: str
    kind: str
    message: str
    created_at: datetime
    read: bool = False
