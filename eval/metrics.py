"""Turn one agent report into the assignment's evaluation metrics.

Each metric answers one question, so we can see *where* a run broke:

retrieval        did the agent read every ground-truth file?
diagnosis        does the evidence point at the buggy line (±2) AND does the root
                 cause mention the ground-truth key ideas (keyword groups)?
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
        "diagnosis": diagnosis_correct(issue, report, workspace),
        "valid_patch": patch.get("applied") if patch else None,
        "tests_pass": tests_pass,
        "autonomous": bool(tests_pass) if tests else None,
        "steps": len(report.get("steps", [])),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "seconds": report.get("seconds", 0),
        "unsafe_or_invalid": invalid,
    }
