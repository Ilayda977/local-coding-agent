"""Composition root: builds and wires every service."""
from dataclasses import dataclass

from common.clock import SystemClock
from common.ids import IdGenerator
from events import EventBus
from notifications.dispatcher import NotificationDispatcher
from notifications.preferences import PreferenceStore
from notifications.service import NotificationService
from projects.service import ProjectService
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
    preferences: PreferenceStore
    notifications: NotificationService
    dispatcher: NotificationDispatcher


def build_app(clock=None):
    clock = clock or SystemClock()
    bus = EventBus()
    users = UserService(InMemoryRepository("user"), IdGenerator("user"), clock)
    projects = ProjectService(InMemoryRepository("project"), users,
                              IdGenerator("project"), clock, bus)
    tasks = TaskService(InMemoryRepository("task"), projects, users,
                        IdGenerator("task"), clock, bus)
    preferences = PreferenceStore()
    notifications = NotificationService(InMemoryRepository("notification"), preferences,
                                        IdGenerator("notification"), clock)
    dispatcher = NotificationDispatcher(bus, notifications, tasks, projects)
    return App(clock=clock, bus=bus, users=users, projects=projects, tasks=tasks,
               preferences=preferences, notifications=notifications, dispatcher=dispatcher)
