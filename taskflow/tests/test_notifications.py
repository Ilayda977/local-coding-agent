import pytest

from common.errors import PermissionDeniedError
from notifications import models
from notifications.preferences import Preferences, in_quiet_hours
from tasks.models import Status


def test_assignment_notifies_assignee(app, project, alice, bob):
    app.tasks.create(project.id, alice.id, "Review PR", assignee_id=bob.id)
    [assigned] = [n for n in app.notifications.unread(bob.id) if n.kind == models.TASK_ASSIGNED]
    assert "Review PR" in assigned.message


def test_self_assignment_does_not_notify(app, project, bob):
    app.tasks.create(project.id, bob.id, "My own task", assignee_id=bob.id)
    assert [n.kind for n in app.notifications.unread(bob.id)] == [models.PROJECT_INVITE]


def test_new_member_gets_project_invite(app, project, carol):
    kinds = [n.kind for n in app.notifications.unread(carol.id)]
    assert kinds == [models.PROJECT_INVITE]


def test_mark_read_decreases_unread_count(app, project, alice, bob):
    app.tasks.create(project.id, alice.id, "One", assignee_id=bob.id)
    app.tasks.create(project.id, alice.id, "Two", assignee_id=bob.id)
    before = app.notifications.unread_count(bob.id)
    first = app.notifications.unread(bob.id)[0]
    app.notifications.mark_read(first.id, bob.id)
    assert app.notifications.unread_count(bob.id) == before - 1


def test_cannot_mark_other_users_notification(app, project, alice, bob):
    app.tasks.create(project.id, alice.id, "One", assignee_id=bob.id)
    notification = app.notifications.unread(bob.id)[0]
    with pytest.raises(PermissionDeniedError):
        app.notifications.mark_read(notification.id, alice.id)


def test_muted_kind_is_not_delivered(app, project, alice, bob):
    app.preferences.mute(bob.id, models.TASK_ASSIGNED)
    app.tasks.create(project.id, alice.id, "Quiet", assignee_id=bob.id)
    assert [n.kind for n in app.notifications.unread(bob.id)] == [models.PROJECT_INVITE]


def test_completion_notifies_creator(app, project, alice, bob):
    task = app.tasks.create(project.id, alice.id, "Ship it", assignee_id=bob.id)
    for status in (Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE):
        app.tasks.change_status(task.id, bob.id, status)
    kinds = [n.kind for n in app.notifications.unread(alice.id)]
    assert kinds == [models.TASK_COMPLETED]


def test_email_skipped_during_quiet_hours(app, project, alice, bob, clock):
    app.preferences.set_email(bob.id, True)
    app.preferences.set_quiet_hours(bob.id, 8, 10)  # clock is at 09:00
    app.tasks.create(project.id, alice.id, "Silent", assignee_id=bob.id)
    assert app.notifications.email_outbox == []
    clock.advance(hours=2)
    app.tasks.create(project.id, alice.id, "Loud", assignee_id=bob.id)
    assert app.notifications.email_outbox == [(bob.id, "You were assigned 'Loud'")]


@pytest.mark.parametrize("hour, expected", [(23, True), (2, True), (7, False), (12, False)])
def test_quiet_hours_wrap_past_midnight(hour, expected):
    assert in_quiet_hours(Preferences(quiet_hours=(22, 7)), hour) is expected


def test_reassignment_notifies_the_new_assignee(app, project, alice, bob):
    carol = app.users.register("dave@taskflow.dev", "Dave")
    app.projects.add_member(project.id, alice.id, carol.id)
    task = app.tasks.create(project.id, alice.id, "Handover", assignee_id=bob.id)
    app.tasks.assign(task.id, alice.id, carol.id)
    assigned = lambda user: [n for n in app.notifications.unread(user.id)
                             if n.kind == models.TASK_ASSIGNED]
    assert len(assigned(carol)) == 1
    assert len(assigned(bob)) == 1  # only the original assignment


def test_deactivated_users_receive_nothing(app, project, admin, alice, bob):
    task = app.tasks.create(project.id, alice.id, "Ship it", assignee_id=bob.id)
    app.projects.add_member(project.id, alice.id, admin.id)
    app.users.deactivate(alice.id, actor_id=admin.id)
    before = app.notifications.unread_count(alice.id)
    for status in (Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE):
        app.tasks.change_status(task.id, bob.id, status)
    app.comments.add(task.id, bob.id, "Done, thanks @alice")
    assert app.notifications.unread_count(alice.id) == before


def test_quiet_hours_are_stored_as_given(app, bob):
    app.preferences.set_quiet_hours(bob.id, 22, 7)
    assert app.preferences.get(bob.id).quiet_hours == (22, 7)
