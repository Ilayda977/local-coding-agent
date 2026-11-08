from datetime import date

import pytest

from common.errors import PermissionDeniedError, ValidationError
from tasks.models import Priority, Status


def finish(app, task, actor):
    for status in (Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE):
        app.tasks.change_status(task.id, actor.id, status)


def test_create_task_defaults(app, project, bob, clock):
    task = app.tasks.create(project.id, bob.id, "  Write docs  ")
    assert task.title == "Write docs"
    assert task.status == Status.TODO
    assert task.priority == Priority.MEDIUM
    assert task.created_at == clock.now()


def test_viewer_cannot_create_task(app, project, carol):
    with pytest.raises(PermissionDeniedError):
        app.tasks.create(project.id, carol.id, "Not allowed")


def test_assignee_must_be_project_member(app, project, bob, admin):
    with pytest.raises(ValidationError):
        app.tasks.create(project.id, bob.id, "Fix", assignee_id=admin.id)


def test_done_sets_completed_at_and_reopen_clears_it(app, project, bob, clock):
    task = app.tasks.create(project.id, bob.id, "Release")
    finish(app, task, bob)
    assert app.tasks.get(task.id).completed_at == clock.now()
    app.tasks.reopen(task.id, bob.id)
    assert app.tasks.get(task.id).status == Status.TODO
    assert app.tasks.get(task.id).completed_at is None


def test_overdue_tasks_exclude_done(app, project, bob):
    late = app.tasks.create(project.id, bob.id, "Late", due_date=date(2026, 2, 20))
    finished = app.tasks.create(project.id, bob.id, "Finished", due_date=date(2026, 2, 20))
    finish(app, finished, bob)
    assert [t.id for t in app.tasks.overdue_tasks(project.id, bob.id)] == [late.id]


def test_task_due_today_is_not_overdue(app, project, bob):
    task = app.tasks.create(project.id, bob.id, "Today", due_date=date(2026, 3, 2))
    assert not app.tasks.is_overdue(task)
