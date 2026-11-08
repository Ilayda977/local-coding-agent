"""Turn one agent report into the assignment's evaluation metrics.

Each metric answers one question, so we can see *where* a run broke:

retrieval        did the agent read every ground-truth file?
diagnosis        did its evidence cover the buggy line, in the right file?
valid_patch      did it produce a patch that applied and parsed?
tests_pass       did the whole test suite pass at the end?
autonomous       tests pass without a human touching anything
steps            research steps used
prompt_tokens    total context sent to the model (Phase 5's cost metric)
unsafe_or_invalid  refused paths + invalid model replies + rejected evidence/patches
"""


def bug_lines(issue, workspace):
    """Line numbers of the injected bug inside the prepared workspace."""
    bug = issue["bug"]
    text = (workspace / bug["file"]).read_text()
    offset = text.index(bug["replace"])
    first = text.count("\n", 0, offset) + 1
    last = first + max(bug["replace"].count("\n") - 1, 0)
    return bug["file"], first, last


def diagnosis_hits_bug(issue, report, workspace):
    diagnosis = report.get("diagnosis")
    if not diagnosis:
        return None if report.get("status") in {"started", "researched"} else False
    file, first, last = bug_lines(issue, workspace)
    for ev in diagnosis.get("evidence", []):
        if ev["file"] == file and ev["start_line"] <= last and ev["end_line"] >= first:
            # Evidence should point at the bug, not at a whole file.
            return (ev["end_line"] - ev["start_line"]) <= 40
    return False


def score(issue, report, workspace):
    truth = set(issue["ground_truth"]["relevant_files"])
    patch = report.get("patch") or {}
    tests = report.get("tests") or {}
    usage = report.get("usage", {})
    invalid = (len(report.get("blocked_paths", [])) + usage.get("invalid_replies", 0)
               + report.get("rejected_evidence", 0) + patch.get("rejected", 0))
    tests_pass = tests.get("passed") if tests else None
    return {
        "retrieval": truth.issubset(report.get("files_read", [])),
        "diagnosis": diagnosis_hits_bug(issue, report, workspace),
        "valid_patch": patch.get("applied") if patch else None,
        "tests_pass": tests_pass,
        "autonomous": bool(tests_pass) if tests else None,
        "steps": len(report.get("steps", [])),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "seconds": report.get("seconds", 0),
        "unsafe_or_invalid": invalid,
    }
