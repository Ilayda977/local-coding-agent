"""run_tests allowlist, the repair loop and the hard limits (Phase 4)."""
from dataclasses import replace

import pytest

from lca import agent
from lca.llm import LLMError
from lca.testing import run_tests, validate_targets
from lca.tools import Repo, ToolError
from tests.conftest import make_llm
from tests.fakes import act
from tests.test_patching import DIAGNOSIS, OLD, OVERDUE_FIXED, inject_bug

# Real names, wrong logic: only the tests can tell that this is wrong.
WRONG_FIX = OLD.replace("< today)", "< today\n                and task.status == Status.DONE)")


# --- run_tests on its own -------------------------------------------------------

def test_clean_repo_passes(repo):
    result = run_tests(repo)
    assert result.passed and result.failed == [] and "passed" in result.summary


def test_failures_are_listed_with_file_and_line(repo):
    inject_bug(repo.root)
    result = run_tests(repo)
    assert not result.passed
    assert result.failed == ["tests/test_tasks.py::test_overdue_tasks_exclude_done"]
    assert "tests/test_tasks.py:" in result.brief
    assert "Warning" not in result.brief


def test_only_test_paths_are_allowed(repo):
    assert validate_targets(repo, ["tests/test_tasks.py::test_create_task_defaults"])
    for bad in ["--version", "tasks/service.py", "../outside/test_x.py", "-k foo"]:
        with pytest.raises(ToolError):
            validate_targets(repo, [bad])


def test_hanging_tests_time_out(tmp_path):
    (tmp_path / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(10)\n")
    result = run_tests(Repo(tmp_path), timeout=1)
    assert result.timed_out and not result.passed


# --- repair loop ------------------------------------------------------------------------

def patch_reply(new_text, plan="fix"):
    return {"plan": plan, "edits": [{"file": "tasks/service.py", "old_text": OLD,
                                     "new_text": new_text}]}


def research_and_diagnosis():
    return [act("read_file", path="tasks/service.py", start_line=90, end_line=110),
            act("finish"), DIAGNOSIS]


def test_failed_tests_trigger_a_repair_that_succeeds(taskflow_copy, settings):
    inject_bug(taskflow_copy)
    llm, client = make_llm(settings, research_and_diagnosis() + [
        patch_reply(WRONG_FIX, "inverted condition"),
        {"plan": "invert the check", "edits": [{
            "file": "tasks/service.py", "old_text": "                and task.status == Status.DONE)",
            "new_text": "                and task.status != Status.DONE)"}]},
    ])
    report = agent.run("Done tasks are overdue", taskflow_copy, settings, llm=llm, fix=True,
                       auto_approve=True)
    assert report["status"] == "fixed"
    assert report["tests"]["repairs"] == 1
    assert [run["passed"] for run in report["tests"]["runs"]] == [False, True]
    repair_prompt = client.requests[-1]["messages"][-1]["content"]
    assert "tests still fail" in repair_prompt and "test_overdue_tasks_exclude_done" in repair_prompt


def test_repairs_are_limited_and_files_are_rolled_back(taskflow_copy, settings):
    path = inject_bug(taskflow_copy)
    buggy = path.read_text()
    still_wrong = {"plan": "again", "edits": [{
        "file": "tasks/service.py", "old_text": "and task.status == Status.DONE)",
        "new_text": "and task.status is Status.DONE)"}]}
    worse = {"plan": "again", "edits": [{
        "file": "tasks/service.py", "old_text": "and task.status is Status.DONE)",
        "new_text": "and task.status in (Status.DONE,))"}]}
    llm, _ = make_llm(settings, research_and_diagnosis() + [patch_reply(WRONG_FIX), still_wrong,
                                                            worse])
    report = agent.run("Done tasks are overdue", taskflow_copy, settings, llm=llm, fix=True,
                       auto_approve=True)
    assert report["status"] == "tests_failed"
    assert report["tests"]["repairs"] == settings.max_repairs == 2
    assert len(report["tests"]["runs"]) == 3
    assert report["patch"]["rolled_back"]
    assert path.read_text() == buggy  # clean stop: the user's files are as before


def test_global_model_call_budget_stops_everything(taskflow_copy, settings):
    settings = replace(settings, max_model_calls=3, max_steps=50)
    llm, _ = make_llm(settings, [act("search_code", query=f"q{n}") for n in range(10)])
    report = agent.run("anything", taskflow_copy, settings, llm=llm)
    assert report["status"] == "model_error"
    assert "budget" in report["error"]
    assert report["usage"]["model_calls"] == 3


def test_reproduce_first_shows_failing_tests_to_the_model(taskflow_copy, settings):
    inject_bug(taskflow_copy)
    settings = replace(settings, reproduce_first=True)
    llm, client = make_llm(settings, research_and_diagnosis())
    report = agent.run("Done tasks are overdue", taskflow_copy, settings, llm=llm)
    assert report["tests_before"]["failed"] == ["tests/test_tasks.py::test_overdue_tasks_exclude_done"]
    first_prompt = client.requests[0]["messages"][1]["content"]
    assert "Test run BEFORE any change" in first_prompt


def test_llm_error_is_raised_when_budget_is_zero(settings):
    llm, _ = make_llm(replace(settings, max_model_calls=0), [])
    from lca.research import Action
    with pytest.raises(LLMError):
        llm.chat_json([{"role": "user", "content": "x"}], {}, "s", Action)


def test_invented_name_in_a_repair_is_rejected_not_applied(taskflow_copy, settings):
    path = inject_bug(taskflow_copy)
    llm, _ = make_llm(settings, research_and_diagnosis() + [
        patch_reply(WRONG_FIX),
        {"plan": "x", "edits": [{"file": "tasks/service.py",
                                 "old_text": "and task.status == Status.DONE)",
                                 "new_text": "and not task.completed)"}]},
        {"plan": "x", "edits": [{"file": "tasks/service.py",
                                 "old_text": "and task.status == Status.DONE)",
                                 "new_text": "and not task.done_flag)"}]},
    ])
    report = agent.run("Done tasks are overdue", taskflow_copy, settings, llm=llm, fix=True,
                       auto_approve=True)
    assert report["status"] == "tests_failed"
    assert any("do not exist" in r for r in report["patch"]["rejections"])
    assert "completed)" not in path.read_text()
