"""Composition root: builds and wires every service."""
from dataclasses import dataclass

from activity.log import ActivityLog
from comments.service import CommentService
from common.clock import SystemClock
from common.ids import IdGenerator
from events import EventBus
from notifications.dispatcher import NotificationDispatcher
from notifications.preferences import PreferenceStore
from notifications.service import NotificationService
from projects.service import ProjectService
from reports.stats import ProjectReports
from storage.memory import InMemoryRepository
from tasks.service import TaskService
from users.service import UserService


@dataclass
class App:
    clock: object
    bus: EventBus
    users: UserService
    projects: ProjectService
    tasks: TaskService
    comments: CommentService
    preferences: PreferenceStore
    notifications: NotificationService
    dispatcher: NotificationDispatcher
    activity: ActivityLog
    reports: ProjectReports


def build_app(clock=None):
    clock = clock or SystemClock()
    bus = EventBus()
    users = UserService(InMemoryRepository("user"), IdGenerator("user"), clock)
    projects = ProjectService(InMemoryRepository("project"), users,
                              IdGenerator("project"), clock, bus)
    tasks = TaskService(InMemoryRepository("task"), projects, users,
                        IdGenerator("task"), clock, bus)
    comments = CommentService(InMemoryRepository("comment"), tasks, projects, users,
                              IdGenerator("comment"), clock, bus)
    preferences = PreferenceStore()
    notifications = NotificationService(InMemoryRepository("notification"), preferences,
                                        IdGenerator("notification"), clock)
    dispatcher = NotificationDispatcher(bus, notifications, tasks, projects, users)
    activity = ActivityLog(bus, clock)
    reports = ProjectReports(tasks)
    return App(clock=clock, bus=bus, users=users, projects=projects, tasks=tasks,
               comments=comments, preferences=preferences, notifications=notifications,
               dispatcher=dispatcher, activity=activity, reports=reports)
