"""Patch safety: these rules protect the user's files, so they are tested without a model."""
import pytest

from lca import agent
from lca.patching import (PatchError, PatchProposal, build_patch, is_test_file,
                          replace_once)
from tests.conftest import make_llm
from tests.fakes import act

OVERDUE_FIXED = ("        return (task.due_date is not None\n"
                 "                and task.status != Status.DONE\n"
                 "                and task.due_date < today)\n")


def proposal(*edits, plan="Fix it."):
    return PatchProposal.model_validate(
        {"plan": plan, "edits": [{"file": f, "old_text": o, "new_text": n} for f, o, n in edits]})


@pytest.fixture
def buggy(repo):
    """The easy_04 bug, injected into the private copy, and its lines read."""
    path = repo.root / "tasks/service.py"
    path.write_text(path.read_text().replace("                and task.status != Status.DONE\n", ""))
    repo.read_file("tasks/service.py", 90, 110)
    return repo


OLD = "        return (task.due_date is not None\n                and task.due_date < today)\n"


# --- replace_once ---------------------------------------------------------------

def test_exact_replacement_reports_the_line():
    text, first, count = replace_once("a\nb\nc\n", "b\n", "B\n")
    assert (text, first, count) == ("a\nB\nc\n", 2, 2)


def test_ambiguous_old_text_is_rejected():
    with pytest.raises(PatchError, match="2 times"):
        replace_once("x = 1\nx = 1\n", "x = 1", "x = 2")


def test_indentation_mistakes_are_tolerated_and_fixed():
    content = "def f():\n    if a:\n        return 1\n"
    text, first, _ = replace_once(content, "if a:\n    return 1", "if a and b:\n    return 1")
    assert text == "def f():\n    if a and b:\n        return 1\n"
    assert first == 2


def test_missing_old_text_is_rejected():
    with pytest.raises(PatchError, match="not found"):
        replace_once("a\n", "zzz", "y")
    with pytest.raises(PatchError, match="empty"):
        replace_once("a\n", "  ", "y")


# --- build_patch rules ------------------------------------------------------------

def test_valid_patch_produces_a_small_diff(buggy, settings):
    patch = build_patch(proposal(("tasks/service.py", OLD, OVERDUE_FIXED)), buggy, 40)
    diff = patch.diff()
    assert "+                and task.status != Status.DONE" in diff
    assert patch.changed_lines() == 1


def test_tests_cannot_be_edited(buggy):
    buggy.read_file("tests/test_tasks.py", 1, 20)
    with pytest.raises(PatchError, match="test file"):
        build_patch(proposal(("tests/test_tasks.py", "import pytest", "import os")), buggy, 40)
    assert is_test_file("tests/conftest.py") and is_test_file("pkg/test_x.py")
    assert not is_test_file("tasks/service.py")


def test_unread_files_and_outside_paths_are_rejected(buggy):
    with pytest.raises(PatchError, match="never read"):
        build_patch(proposal(("users/service.py", "class UserService:", "class X:")), buggy, 40)
    with pytest.raises(PatchError, match="outside"):
        build_patch(proposal(("../evil.py", "a", "b")), buggy, 40)


def test_unread_lines_in_a_read_file_are_rejected(buggy):
    with pytest.raises(PatchError, match="never read"):
        build_patch(proposal(("tasks/service.py", "class TaskService:", "class TS:")), buggy, 40)


def test_syntax_errors_are_rejected(buggy):
    with pytest.raises(PatchError, match="not be valid Python"):
        build_patch(proposal(("tasks/service.py", OLD, "        return (task.due_date\n")),
                    buggy, 40)


def test_big_changes_and_noops_are_rejected(buggy):
    with pytest.raises(PatchError, match="limit"):
        build_patch(proposal(("tasks/service.py", OLD, OVERDUE_FIXED)), buggy, 0)
    with pytest.raises(PatchError, match="do not change"):
        build_patch(proposal(("tasks/service.py", OLD, OLD)), buggy, 40)


# --- apply / rollback ---------------------------------------------------------------

def test_apply_and_rollback_restore_the_exact_bytes(buggy):
    path = buggy.root / "tasks/service.py"
    original = path.read_text()
    patch = build_patch(proposal(("tasks/service.py", OLD, OVERDUE_FIXED)), buggy, 40)
    patch.apply()
    assert "task.status != Status.DONE" in path.read_text()
    assert patch.rollback() == ["tasks/service.py"]
    assert path.read_text() == original


def test_rollback_refuses_to_overwrite_later_human_edits(buggy):
    path = buggy.root / "tasks/service.py"
    patch = build_patch(proposal(("tasks/service.py", OLD, OVERDUE_FIXED)), buggy, 40)
    patch.apply()
    path.write_text(path.read_text() + "\n# my own change\n")
    with pytest.raises(PatchError, match="modified after"):
        patch.rollback()


def test_apply_refuses_if_file_changed_since_reading(buggy):
    patch = build_patch(proposal(("tasks/service.py", OLD, OVERDUE_FIXED)), buggy, 40)
    path = buggy.root / "tasks/service.py"
    path.write_text("# someone else edited this\n" + path.read_text())
    with pytest.raises(PatchError, match="changed on disk"):
        patch.apply()


# --- the pipeline: approval is required ---------------------------------------------

DIAGNOSIS = {"analysis": "", "issue_summary": "s", "root_cause": "`is_overdue` ignores status.",
             "relevant_files": ["tasks/service.py"], "confidence": "high",
             "evidence": [{"file": "tasks/service.py", "start_line": 99, "end_line": 100,
                           "why": "missing check"}]}


def scripted(settings):
    return make_llm(settings, [
        act("read_file", path="tasks/service.py", start_line=90, end_line=110),
        act("finish"),
        DIAGNOSIS,
        {"plan": "Add the status check.", "edits": [
            {"file": "tasks/service.py", "old_text": OLD, "new_text": OVERDUE_FIXED}]},
    ])


def inject_bug(root):
    path = root / "tasks/service.py"
    path.write_text(path.read_text().replace("                and task.status != Status.DONE\n", ""))
    return path


def test_no_write_without_approval(taskflow_copy, settings):
    path = inject_bug(taskflow_copy)
    before = path.read_text()
    llm, _ = scripted(settings)
    asked = []
    report = agent.run("Done tasks are overdue", taskflow_copy, settings, llm=llm, fix=True,
                       approve=lambda plan, diff: asked.append(diff) or False)
    assert report["status"] == "patch_not_approved"
    assert asked and "+                and task.status" in asked[0]  # the human saw the diff
    assert path.read_text() == before


def test_no_approver_means_no_write(taskflow_copy, settings):
    path = inject_bug(taskflow_copy)
    before = path.read_text()
    llm, _ = scripted(settings)
    report = agent.run("Done tasks are overdue", taskflow_copy, settings, llm=llm, fix=True)
    assert report["status"] == "patch_not_approved"
    assert path.read_text() == before


def test_approved_patch_is_applied(taskflow_copy, settings):
    path = inject_bug(taskflow_copy)
    llm, _ = scripted(settings)
    report = agent.run("Done tasks are overdue", taskflow_copy, settings, llm=llm, fix=True,
                       approve=lambda plan, diff: True)
    assert report["patch"]["applied"]
    assert "task.status != Status.DONE" in path.read_text()


def test_rejected_patch_gets_one_more_try(taskflow_copy, settings):
    inject_bug(taskflow_copy)
    llm, client = make_llm(settings, [
        act("read_file", path="tasks/service.py", start_line=90, end_line=110),
        act("finish"), DIAGNOSIS,
        {"plan": "bad", "edits": [{"file": "tasks/service.py", "old_text": "nope", "new_text": "x"}]},
        {"plan": "good", "edits": [{"file": "tasks/service.py", "old_text": OLD,
                                    "new_text": OVERDUE_FIXED}]},
    ])
    report = agent.run("Done tasks are overdue", taskflow_copy, settings, llm=llm, fix=True,
                       auto_approve=True)
    assert report["patch"]["applied"] and report["patch"]["rejected"] == 1
    assert "previous patch was rejected" in client.requests[-1]["messages"][-1]["content"]
