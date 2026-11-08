"""Controller tests for the research loop, driven by a scripted fake model."""
from dataclasses import replace

import pytest

from lca.llm import LLMError
from lca.research import run_research
from tests.conftest import OVERDUE, make_llm
from tests.fakes import act

ISSUE = "Completed tasks still show up as overdue."


def test_happy_path_search_read_finish(repo, settings):
    llm, client = make_llm(settings, [
        act("find_symbol", name="is_overdue"),
        act("read_file", path="tasks/service.py", start_line=OVERDUE, end_line=OVERDUE + 15),
        act("finish"),
    ])
    research = run_research(ISSUE, repo, llm, settings)
    assert research.finished
    assert [s.status for s in research.steps] == ["ok", "ok", "ok"]
    assert "tasks/service.py" in research.steps[0].observation
    assert repo.read_files() == ["tasks/service.py"]
    # The first prompt already contains the issue and the file list.
    first_user = client.requests[0]["messages"][1]["content"]
    assert ISSUE in first_user and "tasks/workflow.py" in first_user


def test_finish_before_reading_is_refused(repo, settings):
    llm, _ = make_llm(settings, [
        act("finish"),
        act("read_file", path="tasks/service.py", start_line=1, end_line=10),
        act("finish"),
    ])
    research = run_research(ISSUE, repo, llm, settings)
    assert [s.status for s in research.steps] == ["refused", "ok", "ok"]
    assert research.finished


def test_repeated_calls_are_not_executed_twice_and_loop_stops(repo, settings):
    same = act("search_code", query="overdue")
    llm, _ = make_llm(settings, [same, same, same])
    research = run_research(ISSUE, repo, llm, settings)
    assert [s.status for s in research.steps] == ["ok", "repeated", "repeated"]
    assert research.stop_reason.startswith("stuck")
    assert not research.finished


def test_step_budget_is_enforced(repo, settings):
    settings = replace(settings, max_steps=3)
    llm, _ = make_llm(settings, [act("search_code", query=f"word{n}") for n in range(3)])
    research = run_research(ISSUE, repo, llm, settings)
    assert len(research.steps) == 3
    assert "budget" in research.stop_reason


def test_tool_errors_become_observations(repo, settings):
    llm, _ = make_llm(settings, [
        act("read_file", path="../../etc/passwd"),
        act("read_file", path="tasks/service.py", start_line=1, end_line=5),
        act("finish"),
    ])
    research = run_research(ISSUE, repo, llm, settings)
    assert research.steps[0].status == "error"
    assert "outside the repository" in research.steps[0].observation
    assert repo.blocked == ["../../etc/passwd"]


def test_long_observations_are_cut(repo, settings):
    settings = replace(settings, max_observation_chars=200)
    llm, _ = make_llm(settings, [act("search_code", query="self"), act("read_file", path="app.py"),
                                 act("finish")])
    research = run_research(ISSUE, repo, llm, settings)
    assert "more characters cut" in research.steps[0].observation


def test_invalid_json_gets_one_retry(repo, settings):
    llm, client = make_llm(settings, [
        "this is not json",
        act("read_file", path="app.py", start_line=1, end_line=3),
        act("finish"),
    ])
    research = run_research(ISSUE, repo, llm, settings)
    assert research.finished
    retry_prompt = client.requests[1]["messages"][-1]["content"]
    assert "invalid" in retry_prompt
    assert llm.usage()["invalid_replies"] == 1


def test_two_invalid_replies_raise(repo, settings):
    llm, _ = make_llm(settings, ["nope", {"tool": "rm -rf"}])
    with pytest.raises(LLMError):
        run_research(ISSUE, repo, llm, settings)


def test_rereading_known_lines_counts_as_repeat(repo, settings):
    llm, _ = make_llm(settings, [
        act("read_file", path="tasks/service.py", start_line=OVERDUE - 6, end_line=OVERDUE + 14),
        act("read_file", path="tasks/service.py", start_line=OVERDUE - 1, end_line=OVERDUE + 4),
        act("finish"),
    ])
    research = run_research(ISSUE, repo, llm, settings)
    assert [s.status for s in research.steps] == ["ok", "repeated", "ok"]


def test_thought_length_is_limited_in_the_schema():
    from lca.research import ACTION_SCHEMA
    assert ACTION_SCHEMA["properties"]["thought"]["maxLength"] == 200
