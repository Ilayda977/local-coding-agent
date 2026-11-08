import pytest

from common.errors import ConflictError, PermissionDeniedError, ValidationError
from projects.models import ProjectRole


def test_creator_is_owner(app, alice):
    project = app.projects.create(alice.id, "  Mobile app ")
    assert project.name == "Mobile app"
    assert project.members == {alice.id: ProjectRole.OWNER}


def test_non_owner_cannot_add_member(app, project, bob, admin):
    with pytest.raises(PermissionDeniedError):
        app.projects.add_member(project.id, bob.id, admin.id)


def test_adding_existing_member_conflicts(app, project, alice, bob):
    with pytest.raises(ConflictError):
        app.projects.add_member(project.id, alice.id, bob.id)


def test_owner_cannot_be_removed(app, project, alice):
    with pytest.raises(ValidationError):
        app.projects.remove_member(project.id, alice.id, alice.id)


def test_removed_member_loses_access(app, project, alice, bob):
    app.projects.remove_member(project.id, alice.id, bob.id)
    with pytest.raises(PermissionDeniedError):
        app.projects.get_for_user(project.id, bob.id)


def test_archived_project_is_read_only(app, project, alice, bob):
    app.projects.archive(project.id, alice.id)
    with pytest.raises(PermissionDeniedError):
        app.tasks.create(project.id, bob.id, "Late change")
    assert app.projects.get_for_user(project.id, bob.id).archived


def test_list_for_user_only_returns_member_projects(app, project, alice, admin):
    other = app.projects.create(admin.id, "Internal")
    assert [p.id for p in app.projects.list_for_user(alice.id)] == [project.id]
    app.projects.archive(other.id, admin.id)
    assert app.projects.list_for_user(admin.id) == []
    assert len(app.projects.list_for_user(admin.id, include_archived=True)) == 1


def test_removed_member_tasks_become_unassigned(app, project, alice, bob):
    mine = app.tasks.create(project.id, alice.id, "Bob's task", assignee_id=bob.id)
    other = app.tasks.create(project.id, alice.id, "Alice's task", assignee_id=alice.id)
    app.projects.remove_member(project.id, alice.id, bob.id)
    assert app.tasks.get(mine.id).assignee_id is None
    assert app.tasks.get(other.id).assignee_id == alice.id
