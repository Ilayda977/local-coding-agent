from datetime import datetime, timezone

import pytest

from app import build_app
from common.clock import FixedClock
from projects.models import ProjectRole
from users.models import Role


@pytest.fixture
def clock():
    # Monday 2 March 2026, 09:00 UTC
    return FixedClock(datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc))


@pytest.fixture
def app(clock):
    return build_app(clock)


@pytest.fixture
def admin(app):
    return app.users.register("admin@taskflow.dev", "Admin", role=Role.ADMIN)


@pytest.fixture
def alice(app):
    return app.users.register("alice@taskflow.dev", "Alice")


@pytest.fixture
def bob(app):
    return app.users.register("bob@taskflow.dev", "Bob")


@pytest.fixture
def carol(app):
    return app.users.register("carol@taskflow.dev", "Carol")


@pytest.fixture
def project(app, alice, bob, carol):
    """Alice owns the project, Bob is an editor, Carol a viewer."""
    project = app.projects.create(alice.id, "Website")
    app.projects.add_member(project.id, alice.id, bob.id, ProjectRole.EDITOR)
    app.projects.add_member(project.id, alice.id, carol.id, ProjectRole.VIEWER)
    return project
