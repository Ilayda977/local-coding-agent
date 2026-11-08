from tasks.models import Status


def test_status_change_records_old_and_new_status(app, project, bob):
    task = app.tasks.create(project.id, bob.id, "Deploy")
    app.tasks.change_status(task.id, bob.id, Status.IN_PROGRESS)
    [entry] = app.activity.for_subject(task.id)
    assert entry.kind == "status"
    assert entry.detail == "todo -> in_progress"
    assert entry.actor_id == bob.id


def test_membership_and_comments_are_logged(app, project, alice, bob):
    task = app.tasks.create(project.id, alice.id, "Docs")
    app.comments.add(task.id, bob.id, "Hi")
    app.projects.remove_member(project.id, alice.id, bob.id)
    kinds = [entry.kind for entry in app.activity.recent()]
    assert kinds[:2] == ["member_removed", "comment"]
    assert "member_added" in kinds
