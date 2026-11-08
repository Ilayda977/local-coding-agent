"""Turn one agent report into the assignment's evaluation metrics.

Each metric answers one question, so we can see *where* a run broke:

retrieval        did the agent read every ground-truth file?
diagnosis        does the evidence point at the buggy line (±2) AND does the root
                 cause mention the ground-truth key ideas (keyword groups)?
valid_patch      did it produce a patch that applied and parsed?
tests_pass       did the whole test suite pass at the end? (run by the evaluator)
autonomous       tests pass without a human touching anything
steps            research steps used
prompt_tokens    total context sent to the model (Phase 5's cost metric)
unsafe_or_invalid  refused paths + invalid model replies + rejected evidence/patches
"""


def bug_lines(issue, workspace=None):
    """Line numbers of the injected bug, as the agent saw them before any patch.

    Computed from the clean taskflow file with the bug applied in memory, so it
    still works after the agent has (hopefully) fixed the workspace.
    """
    from issues import TASKFLOW  # eval/issues.py
    bug = issue["bug"]
    clean = (TASKFLOW / bug["file"]).read_text()
    text = clean.replace(bug["find"], bug["replace"], 1)
    offset = text.index(bug["replace"])
    first = text.count("\n", 0, offset) + 1
    last = first + max(bug["replace"].count("\n") - 1, 0)
    return bug["file"], first, last


LINE_TOLERANCE = 2  # small models are often off by a line or two (e.g. cite a blank line)


def evidence_hits_bug(issue, report, workspace):
    """Does at least one evidence range point at (or right next to) the bug?"""
    file, first, last = bug_lines(issue, workspace)
    for ev in report["diagnosis"].get("evidence", []):
        near = (ev["start_line"] <= last + LINE_TOLERANCE
                and ev["end_line"] >= first - LINE_TOLERANCE)
        # Evidence should point at the bug, not at a whole file.
        if ev["file"] == file and near and ev["end_line"] - ev["start_line"] <= 40:
            return True
    return False


def root_cause_matches(issue, report):
    """Every keyword group of the ground truth must appear in the root cause.

    A transparent, reproducible proxy for "is the explanation right?". It is
    not perfect, so the final report also contains a human review.
    """
    text = report["diagnosis"]["root_cause"].lower()
    groups = issue["ground_truth"].get("keywords", [])
    return all(any(word.lower() in text for word in group) for group in groups)


def diagnosis_correct(issue, report, workspace):
    if not report.get("diagnosis"):
        return None if report.get("status") in {"started", "researched"} else False
    return evidence_hits_bug(issue, report, workspace) and root_cause_matches(issue, report)


def evaluator_tests_pass(report, workspace):
    """Run the test suite ourselves after the agent finished.

    We do not trust the agent's own claim: the evaluator checks the final state
    of the workspace. ``None`` when no patch was applied (nothing to test).
    """
    from issues import failing_tests  # eval/issues.py
    patch = report.get("patch") or {}
    if not patch.get("applied"):
        return None
    return not failing_tests(workspace)


def score(issue, report, workspace, run_tests=True):
    truth = set(issue["ground_truth"]["relevant_files"])
    patch = report.get("patch") or {}
    usage = report.get("usage", {})
    invalid = (len(report.get("blocked_paths", [])) + usage.get("invalid_replies", 0)
               + report.get("rejected_evidence", 0) + patch.get("rejected", 0))
    tests_pass = evaluator_tests_pass(report, workspace) if run_tests else None
    if patch and not patch.get("applied"):
        tests_pass = False  # a fix was attempted but nothing usable was applied
    return {
        "retrieval": truth.issubset(report.get("files_read", [])),
        "diagnosis": diagnosis_correct(issue, report, workspace),
        "valid_patch": patch.get("applied") if patch else None,
        "tests_pass": tests_pass,
        # Autonomous = fixed with no human help (eval auto-approves the patch).
        "autonomous": bool(tests_pass) if tests_pass is not None else None,
        "steps": len(report.get("steps", [])),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "seconds": report.get("seconds", 0),
        "unsafe_or_invalid": invalid,
    }
