"""Diagnosis grounding: the controller must catch unread, invented or vague evidence."""
from lca import agent
from lca.diagnosis import Diagnosis, Evidence, check, referenced_names
from tests.conftest import make_llm
from tests.fakes import act

ISSUE = "Completed tasks still show up as overdue."


def diagnosis(evidence, root_cause="`is_overdue` ignores the status.", files=("tasks/service.py",)):
    return {"issue_summary": ISSUE, "root_cause": root_cause, "relevant_files": list(files),
            "evidence": evidence, "confidence": "high"}


def ev(file="tasks/service.py", start=97, end=101):
    return {"file": file, "start_line": start, "end_line": end, "why": "condition"}


# --- check() on its own -------------------------------------------------------

def test_grounded_diagnosis_passes_and_gets_real_code(repo):
    repo.read_file("tasks/service.py", 95, 105)
    d = Diagnosis.model_validate(diagnosis([ev()]))
    assert check(d, repo) == []
    assert "and task.status != Status.DONE" in d.evidence[0].code  # copied from disk


def test_unread_lines_are_rejected(repo):
    repo.read_file("tasks/service.py", 1, 20)
    problems = check(Diagnosis.model_validate(diagnosis([ev()])), repo)
    assert any("did not read" in p for p in problems)


def test_missing_file_and_bad_range_are_rejected(repo):
    repo.read_file("tasks/service.py", 95, 105)
    d = Diagnosis.model_validate(diagnosis([ev(file="tasks/ghost.py"), ev(start=105, end=95)]))
    problems = check(d, repo)
    assert any("does not exist" in p for p in problems)
    assert any("invalid line range" in p for p in problems)


def test_whole_file_evidence_is_rejected(repo):
    repo.read_file("tasks/service.py", 1, 80)
    problems = check(Diagnosis.model_validate(diagnosis([ev(start=1, end=80)])), repo)
    assert any("too large" in p for p in problems)


def test_invented_function_names_are_rejected(repo):
    repo.read_file("tasks/service.py", 95, 105)
    d = Diagnosis.model_validate(diagnosis([ev()], root_cause="`check_deadline()` is wrong."))
    assert any("check_deadline" in p for p in check(d, repo))


def test_empty_evidence_is_rejected(repo):
    assert check(Diagnosis.model_validate(diagnosis([])), repo)


def test_referenced_names_extraction():
    names = referenced_names("In `TaskService.is_overdue` the call due_date.compare() and "
                             "self.x are used; return True.")
    assert {"TaskService", "is_overdue", "compare", "due_date"} <= names
    assert "self" not in names and "True" not in names


def test_evidence_file_is_added_to_relevant_files(repo):
    repo.read_file("tasks/service.py", 95, 105)
    d = Diagnosis.model_validate(diagnosis([ev()], files=[]))
    assert check(d, repo) == []
    assert d.relevant_files == ["tasks/service.py"]


# --- the whole pipeline with a scripted model ----------------------------------

def test_pipeline_produces_grounded_diagnosis(taskflow_copy, settings):
    llm, _ = make_llm(settings, [
        act("find_symbol", name="is_overdue"),
        act("read_file", path="tasks/service.py", start_line=95, end_line=105),
        act("finish"),
        diagnosis([ev()]),
    ])
    report = agent.run(ISSUE, taskflow_copy, settings, llm=llm)
    assert report["status"] == "diagnosed"
    assert report["diagnosis"]["evidence"][0]["code"]
    assert report["rejected_evidence"] == 0


def test_rejected_diagnosis_sends_agent_back_to_read(taskflow_copy, settings):
    llm, client = make_llm(settings, [
        act("read_file", path="tasks/service.py", start_line=1, end_line=20),
        act("finish"),
        diagnosis([ev()]),                       # cites lines 97-101: not read yet
        act("read_file", path="tasks/service.py", start_line=95, end_line=105),
        act("finish"),
        diagnosis([ev()]),                       # now grounded
    ])
    report = agent.run(ISSUE, taskflow_copy, settings, llm=llm)
    assert report["status"] == "diagnosed"
    assert report["rejected_evidence"] == 1
    feedback = [m["content"] for m in client.requests[3]["messages"] if m["role"] == "user"][-1]
    assert "rejected by the controller" in feedback


def test_persistent_bad_evidence_ends_as_insufficient(taskflow_copy, settings):
    bad = diagnosis([ev(file="tasks/ghost.py")])
    llm, _ = make_llm(settings, [
        act("read_file", path="tasks/service.py", start_line=1, end_line=20),
        act("finish"), bad, act("finish"), bad,
    ])
    report = agent.run(ISSUE, taskflow_copy, settings, llm=llm)
    assert report["status"] == "insufficient_evidence"
    assert report["rejected_evidence"] == 2
    assert "diagnosis" not in report


def test_no_reading_means_no_diagnosis(taskflow_copy, settings):
    from dataclasses import replace
    settings = replace(settings, max_steps=2)
    llm, _ = make_llm(settings, [act("search_code", query="a"), act("search_code", query="b")])
    report = agent.run(ISSUE, taskflow_copy, settings, llm=llm)
    assert report["status"] == "insufficient_evidence"
