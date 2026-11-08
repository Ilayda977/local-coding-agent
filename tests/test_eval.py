"""The evaluation harness itself: a wrong metric would make every result wrong."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

import issues  # noqa: E402
import metrics  # noqa: E402


def by_id(issue_id):
    return next(i for i in issues.load_issues() if i["id"] == issue_id)


def test_dataset_has_five_issues_per_difficulty():
    levels = [i["difficulty"] for i in issues.load_issues()]
    assert {level: levels.count(level) for level in set(levels)} == \
        {"easy": 5, "medium": 5, "hard": 5}


def test_bug_location_is_the_line_the_agent_sees():
    issue = by_id("easy_03")
    [(file, first, last)] = metrics.bug_locations(issue)
    buggy = issues.TASKFLOW.joinpath(file).read_text().replace(
        issue["bug"]["find"], issue["bug"]["replace"])
    assert buggy.splitlines()[first - 1].strip() == "Status.BLOCKED: {Status.TODO},"


def report_with(evidence, root_cause):
    return {"status": "diagnosed", "diagnosis": {"root_cause": root_cause, "evidence": evidence}}


def test_diagnosis_needs_location_and_key_ideas():
    issue = by_id("easy_03")
    [(file, line, _)] = metrics.bug_locations(issue)
    near = [{"file": file, "start_line": line + 1, "end_line": line + 2}]
    far = [{"file": file, "start_line": line + 10, "end_line": line + 12}]
    good = "ALLOWED_TRANSITIONS for BLOCKED lacks IN_PROGRESS"
    assert metrics.diagnosis_correct(issue, report_with(near, good), None)
    assert not metrics.diagnosis_correct(issue, report_with(far, good), None)
    assert not metrics.diagnosis_correct(issue, report_with(near, "ensure_transition is wrong"), None)


def test_deletion_bugs_have_a_location():
    [(file, first, last)] = metrics.bug_locations(by_id("hard_01"))
    assert file == "notifications/dispatcher.py" and first == last


def test_every_bug_breaks_exactly_its_tests():
    assert issues.check()
