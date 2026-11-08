"""Phase 2: turn what the agent read into a grounded diagnosis.

The model writes the explanation. The controller checks the *facts* in it:

* every evidence range must point at lines the agent really read,
* files must exist, ranges must be small and inside the file,
* names the model mentions (`foo`, Foo.bar, foo()) must exist in the code.

If a check fails, the problems are sent back so the agent can read more or
correct itself, at most ``max_evidence_retries`` times. We never "fix" a
diagnosis silently: what the user sees is what the model said, plus the
real code lines the controller copied from disk.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field

from lca import prompts

MAX_EVIDENCE_LINES = 30

DIAGNOSIS_SCHEMA = {
    "type": "object",
    "properties": {
        # Listed first on purpose: the model writes its step-by-step check
        # *before* committing to a root cause (a small "think first" slot).
        "analysis": {"type": "string", "maxLength": 1200},
        "issue_summary": {"type": "string"},
        "root_cause": {"type": "string"},
        "relevant_files": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["file", "start_line", "end_line", "why"],
            },
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["analysis", "issue_summary", "root_cause", "relevant_files", "evidence",
                 "confidence"],
}


class Evidence(BaseModel):
    file: str
    start_line: int
    end_line: int
    why: str = ""
    code: str = ""  # filled by the controller from disk, never by the model


class Diagnosis(BaseModel):
    analysis: str = ""
    issue_summary: str
    root_cause: str
    relevant_files: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    # A word, not a percentage: a model's "0.87" would look more precise than it is.
    confidence: Literal["low", "medium", "high"] = "low"


# Things in the root cause that look like code references.
_BACKTICKED = re.compile(r"`([^`]+)`")
_CALL_OR_DOTTED = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+|[A-Za-z_][A-Za-z0-9_]*(?=\())")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Words that look like code but are Python itself, not the repository.
_BUILTINS = {"self", "None", "True", "False", "len", "list", "dict", "set", "str", "int",
             "print", "sorted", "range", "return", "if", "not", "and", "or", "lambda"}


def ask_diagnosis(llm, issue, repo, previous_problems=None):
    """A fresh, focused conversation: bug report + the code that was read."""
    task = prompts.diagnosis_task(issue, repo.code_pack())
    if previous_problems:
        task += "\n\nA previous diagnosis was rejected because:\n" + "\n".join(
            f"- {p}" for p in previous_problems)
    messages = [{"role": "system", "content": prompts.DIAGNOSIS_SYSTEM},
                {"role": "user", "content": task}]
    return llm.chat_json(messages, DIAGNOSIS_SCHEMA, "diagnosis", Diagnosis, num_predict=1000)


def referenced_names(text):
    """Code-like names mentioned in free text: `x`, a.b, call()."""
    names = set()
    for snippet in _BACKTICKED.findall(text):
        names.update(_IDENTIFIER.findall(snippet))
    for match in _CALL_OR_DOTTED.findall(text):
        names.update(match.split("."))
    return {n for n in names if n not in _BUILTINS and not n.isdigit() and len(n) > 1}


def check(diagnosis, repo):
    """Return a list of problems (empty list = the diagnosis is grounded).

    Side effect on success: evidence ``code`` is filled with the real lines,
    and files that appear in evidence are added to relevant_files.
    """
    problems = []
    if not diagnosis.evidence:
        problems.append("evidence is empty: cite at least one line range you read")
    for ev in diagnosis.evidence:
        label = f"{ev.file}:{ev.start_line}-{ev.end_line}"
        try:
            path = repo.resolve(ev.file)
        except Exception:  # ToolError: outside the repo or ignored folder
            problems.append(f"{label}: file is not inside the repository")
            continue
        if not path.is_file():
            problems.append(f"{label}: file does not exist")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if not 1 <= ev.start_line <= ev.end_line <= len(lines):
            problems.append(f"{label}: invalid line range (file has {len(lines)} lines)")
            continue
        if ev.end_line - ev.start_line + 1 > MAX_EVIDENCE_LINES:
            problems.append(f"{label}: range too large; point at the exact faulty lines "
                            f"(max {MAX_EVIDENCE_LINES})")
            continue
        if not repo.was_read(ev.file, ev.start_line, ev.end_line):
            problems.append(f"{label}: you did not read these lines; read them first "
                            "or cite lines you read")
            continue
        ev.file = repo.relative(path)
        ev.code = "\n".join(f"{n} | {lines[n - 1]}"
                            for n in range(ev.start_line, ev.end_line + 1))

    for name in diagnosis.relevant_files:
        try:
            if not repo.resolve(name).is_file():
                problems.append(f"relevant file '{name}' does not exist")
        except Exception:
            problems.append(f"relevant file '{name}' is not inside the repository")

    for name in sorted(referenced_names(diagnosis.root_cause)):
        if not repo.contains_identifier(name):
            problems.append(f"root_cause mentions '{name}', which does not exist in the code")

    if not problems:
        cited = [ev.file for ev in diagnosis.evidence]
        normalized = [repo.relative(repo.resolve(f)) for f in diagnosis.relevant_files]
        diagnosis.relevant_files = list(dict.fromkeys(cited + normalized))
    return problems
