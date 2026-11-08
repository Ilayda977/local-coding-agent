from tasks.models import Status


def finish(app, task, actor):
    for status in (Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE):
        app.tasks.change_status(task.id, actor.id, status)


def test_progress_counts_done_tasks(app, project, bob):
    first = app.tasks.create(project.id, bob.id, "One")
    app.tasks.create(project.id, bob.id, "Two")
    app.tasks.create(project.id, bob.id, "Three")
    finish(app, first, bob)
    progress = app.reports.progress(project.id, bob.id)
    assert (progress.total, progress.done, progress.percent_done) == (3, 1, 33)
    assert progress.by_status == {"done": 1, "todo": 2}


def test_progress_of_empty_project_is_zero(app, project, bob):
    assert app.reports.progress(project.id, bob.id).percent_done == 0


def test_reopened_task_is_no_longer_done(app, project, bob):
    task = app.tasks.create(project.id, bob.id, "Release")
    finish(app, task, bob)
    app.tasks.reopen(task.id, bob.id)
    assert app.reports.progress(project.id, bob.id).done == 0


def test_workload_counts_only_open_tasks(app, project, alice, bob):
    open_task = app.tasks.create(project.id, alice.id, "Open", assignee_id=bob.id)
    finished = app.tasks.create(project.id, alice.id, "Finished", assignee_id=bob.id)
    finish(app, finished, bob)
    app.tasks.change_status(open_task.id, bob.id, Status.IN_PROGRESS)
    assert app.reports.workload(project.id, alice.id) == {bob.id: 1}


def test_blocked_tasks_report(app, project, bob):
    task = app.tasks.create(project.id, bob.id, "Waiting")
    app.tasks.change_status(task.id, bob.id, Status.BLOCKED)
    assert [t.id for t in app.reports.blocked_tasks(project.id, bob.id)] == [task.id]
