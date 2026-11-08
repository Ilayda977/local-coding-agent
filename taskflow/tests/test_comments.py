import pytest

from comments.mentions import extract_mentions
from common.errors import PermissionDeniedError, ValidationError
from notifications import models


def test_extract_mentions_keeps_order_and_ignores_emails():
    text = "Ping @Alice and @bob.smith. Mail me at x@example.com, thanks @alice!"
    assert extract_mentions(text) == ["Alice", "bob.smith"]


def test_comment_mentions_notify_members(app, project, alice, bob):
    task = app.tasks.create(project.id, alice.id, "Design review")
    comment = app.comments.add(task.id, alice.id, "Can you check this @bob?")
    assert comment.mentioned_ids == [bob.id]
    kinds = [n.kind for n in app.notifications.unread(bob.id)]
    assert models.MENTIONED in kinds


def test_mentions_are_case_insensitive(app, project, alice, bob):
    task = app.tasks.create(project.id, alice.id, "Design review")
    comment = app.comments.add(task.id, alice.id, "Thoughts, @Bob?")
    assert comment.mentioned_ids == [bob.id]


def test_mentioning_a_non_member_does_not_notify_them(app, project, alice, admin):
    task = app.tasks.create(project.id, alice.id, "Secret plan")
    comment = app.comments.add(task.id, alice.id, "Maybe @admin knows?")
    assert comment.mentioned_ids == []
    assert app.notifications.unread(admin.id) == []


def test_assignee_hears_about_comments_only_once(app, project, alice, bob):
    task = app.tasks.create(project.id, alice.id, "Fix bug", assignee_id=bob.id)
    app.comments.add(task.id, alice.id, "Any news @bob?")
    kinds = [n.kind for n in app.notifications.unread(bob.id)]
    assert kinds.count(models.MENTIONED) == 1
    assert models.TASK_COMMENTED not in kinds


def test_assignee_is_told_about_plain_comments(app, project, alice, bob):
    task = app.tasks.create(project.id, alice.id, "Fix bug", assignee_id=bob.id)
    app.comments.add(task.id, alice.id, "Reminder: deadline Friday")
    assert models.TASK_COMMENTED in [n.kind for n in app.notifications.unread(bob.id)]


def test_viewers_can_comment_but_outsiders_cannot(app, project, alice, carol, admin):
    task = app.tasks.create(project.id, alice.id, "Docs")
    assert app.comments.add(task.id, carol.id, "Looks good")
    with pytest.raises(PermissionDeniedError):
        app.comments.add(task.id, admin.id, "Hello")


def test_archived_project_rejects_comments(app, project, alice, bob):
    task = app.tasks.create(project.id, alice.id, "Old work")
    app.projects.archive(project.id, alice.id)
    with pytest.raises(PermissionDeniedError):
        app.comments.add(task.id, bob.id, "Late remark")


def test_only_author_edits_and_owner_may_delete(app, project, alice, bob, clock):
    task = app.tasks.create(project.id, alice.id, "Docs")
    comment = app.comments.add(task.id, bob.id, "First draft")
    with pytest.raises(PermissionDeniedError):
        app.comments.edit(comment.id, alice.id, "Hijacked")
    clock.advance(minutes=5)
    assert app.comments.edit(comment.id, bob.id, "Second draft").edited_at == clock.now()
    app.comments.delete(comment.id, alice.id)  # alice owns the project
    assert app.comments.list_for_task(task.id, alice.id) == []


def test_empty_comment_is_rejected(app, project, alice):
    task = app.tasks.create(project.id, alice.id, "Docs")
    with pytest.raises(ValidationError):
        app.comments.add(task.id, alice.id, "   ")
