"""The compact (state summary) prompt used when compact_history=True."""
from dataclasses import replace

from lca.context import state_messages, summarize_step
from lca.research import Step, run_research, start_research
from tests.conftest import OVERDUE, make_llm
from tests.fakes import act

ISSUE = "Completed tasks still show up as overdue."


def test_summaries_are_one_line_and_reads_point_to_the_code_pack():
    read = Step(2, "", "read_file(path='a.py')", "a.py lines 1-20 of 50:\n1 | x = 1", "ok")
    search = Step(1, "", "search_code(query='x')", "6 matches for 'x':\na\nb\nc\nd\ne\nf", "ok")
    assert summarize_step(read) == "2. read_file(path='a.py') -> read a.py lines 1-20 of 50 (code below)"
    assert summarize_step(search).endswith("(+3 more)")
    assert "\n" not in summarize_step(search)


def test_state_prompt_contains_history_code_and_only_latest_result(repo):
    research = start_research(ISSUE, repo)
    repo.read_file("tasks/service.py", OVERDUE, OVERDUE + 5)
    research.steps = [
        Step(1, "", "search_code(query='overdue')", "2 matches for 'overdue':\nX\nY", "ok"),
        Step(2, "", "read_file(path='tasks/service.py')", "tasks/service.py lines 91-110 of 114:", "ok"),
        Step(3, "", "find_symbol(name='is_overdue')", "Definitions of 'is_overdue':\nZ", "ok"),
    ]
    user = state_messages(ISSUE, repo, research)[1]["content"]
    assert "Actions so far:" in user and "1. search_code" in user
    assert "### tasks/service.py" in user          # code pack
    assert "Latest result of find_symbol" in user  # only the last observation in full
    assert "Latest result of search_code" not in user


def test_compact_mode_sends_two_messages_every_step(repo, settings):
    settings = replace(settings, compact_history=True)
    llm, client = make_llm(settings, [
        act("find_symbol", name="is_overdue"),
        act("read_file", path="tasks/service.py", start_line=OVERDUE, end_line=OVERDUE + 5),
        act("finish"),
    ])
    research = run_research(ISSUE, repo, llm, settings)
    assert research.finished
    assert all(len(r["messages"]) == 2 for r in client.requests)
