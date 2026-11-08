from datetime import date

import pytest

from common.errors import ValidationError
from tasks.models import Priority, Status
from tasks.queries import TaskFilter, paginate


def test_sort_by_priority_puts_urgent_first(app, project, bob, clock):
    low = app.tasks.create(project.id, bob.id, "Low", priority=Priority.LOW)
    clock.advance(minutes=1)
    urgent = app.tasks.create(project.id, bob.id, "Urgent", priority=Priority.URGENT)
    clock.advance(minutes=1)
    medium = app.tasks.create(project.id, bob.id, "Medium", priority=Priority.MEDIUM)
    page = app.tasks.search(project.id, bob.id, sort_by="priority")
    assert [t.id for t in page.items] == [urgent.id, medium.id, low.id]


def test_sort_by_due_date_puts_missing_dates_last(app, project, bob):
    none = app.tasks.create(project.id, bob.id, "No date")
    later = app.tasks.create(project.id, bob.id, "Later", due_date=date(2026, 4, 1))
    sooner = app.tasks.create(project.id, bob.id, "Sooner", due_date=date(2026, 3, 5))
    page = app.tasks.search(project.id, bob.id, sort_by="due_date")
    assert [t.id for t in page.items] == [sooner.id, later.id, none.id]


def test_unknown_sort_key_is_rejected(app, project, bob):
    with pytest.raises(ValidationError):
        app.tasks.search(project.id, bob.id, sort_by="title")


def test_paginate_returns_requested_slice():
    page = paginate(list(range(25)), page=3, per_page=10)
    assert page.items == [20, 21, 22, 23, 24]
    assert page.total == 25
    assert page.pages == 3


@pytest.mark.parametrize("page, per_page", [(0, 10), (1, 0), (1, 101)])
def test_paginate_rejects_invalid_arguments(page, per_page):
    with pytest.raises(ValidationError):
        paginate([1, 2, 3], page=page, per_page=per_page)


def test_filter_by_status_and_assignee(app, project, alice, bob):
    mine = app.tasks.create(project.id, alice.id, "Mine", assignee_id=bob.id)
    app.tasks.create(project.id, alice.id, "Unassigned")
    started = app.tasks.create(project.id, alice.id, "Started", assignee_id=bob.id)
    app.tasks.change_status(started.id, bob.id, Status.IN_PROGRESS)
    task_filter = TaskFilter(status=Status.TODO, assignee_id=bob.id)
    page = app.tasks.search(project.id, bob.id, task_filter)
    assert [t.id for t in page.items] == [mine.id]


def test_text_filter_is_case_insensitive(app, project, bob):
    task = app.tasks.create(project.id, bob.id, "Fix Login page")
    app.tasks.create(project.id, bob.id, "Write tests", description="unit and e2e")
    page = app.tasks.search(project.id, bob.id, TaskFilter(text="login"))
    assert [t.id for t in page.items] == [task.id]


def test_search_requires_membership(app, project, admin):
    from common.errors import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        app.tasks.search(project.id, admin.id)
