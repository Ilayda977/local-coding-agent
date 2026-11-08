import pytest

from common.errors import ValidationError
from tasks import workflow
from tasks.models import Status


def test_todo_can_start():
    assert workflow.can_transition(Status.TODO, Status.IN_PROGRESS)


def test_cannot_skip_review():
    assert not workflow.can_transition(Status.IN_PROGRESS, Status.DONE)


def test_blocked_task_can_resume(app, project, bob):
    task = app.tasks.create(project.id, bob.id, "Deploy")
    app.tasks.change_status(task.id, bob.id, Status.IN_PROGRESS)
    app.tasks.change_status(task.id, bob.id, Status.BLOCKED)
    app.tasks.change_status(task.id, bob.id, Status.IN_PROGRESS)
    assert app.tasks.get(task.id).status == Status.IN_PROGRESS


def test_done_cannot_move_back_without_reopen():
    with pytest.raises(ValidationError):
        workflow.ensure_transition(Status.DONE, Status.IN_PROGRESS)


def test_same_status_is_rejected():
    with pytest.raises(ValidationError):
        workflow.ensure_transition(Status.TODO, Status.TODO)
