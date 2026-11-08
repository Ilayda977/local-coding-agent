"""The pipeline: research -> diagnosis -> (plan + patch -> test -> repair).

This file only *orchestrates*. Each stage lives in its own module so it can be
understood and tested on its own. The result is a plain dict (the "report")
that both the CLI and the evaluation script consume.

Status values a report can end with:
  diagnosed              grounded diagnosis, no patch requested
  insufficient_evidence  the agent could not back its explanation with code it read
  model_error            the model kept producing invalid output / was unreachable
"""
import time
from pathlib import Path

from lca import diagnosis as diag
from lca import prompts
from lca.llm import LLM, LLMError
from lca.research import run_research
from lca.tools import Repo


def run(issue, repo_path, settings, *, llm=None, on_step=None, on_token=None,
        auto_approve=False, events=None):
    """Investigate ``issue`` in ``repo_path`` and return a report dict.

    ``events`` is an optional callback ``events(kind, data)`` the CLI uses to
    show progress (e.g. "diagnosis rejected, reading more").
    """
    started = time.monotonic()
    notify = events or (lambda kind, data: None)
    repo = Repo(Path(repo_path), max_read_lines=settings.max_read_lines,
                max_search_results=settings.max_search_results,
                min_read_lines=settings.min_read_lines)
    llm = llm or LLM(settings, on_token=on_token)
    report = {"issue": issue, "model": settings.model, "repo": str(repo.root),
              "status": "started", "steps": [], "rejected_evidence": 0}
    try:
        research = run_research(issue, repo, llm, settings, on_step=on_step)
        result, problems = _diagnose(issue, repo, llm, settings, research, report, notify,
                                     on_step)
        report["steps"] = [vars(step) for step in research.steps]
        report["stop_reason"] = research.stop_reason
        if result is None:
            report["status"] = "insufficient_evidence"
            report["diagnosis_problems"] = problems
        else:
            report["status"] = "diagnosed"
            report["diagnosis"] = result.model_dump()
    except LLMError as error:
        report["status"] = "model_error"
        report["error"] = str(error)
    report["files_read"] = repo.read_files()
    report["blocked_paths"] = list(repo.blocked)
    report["usage"] = llm.usage()
    report["seconds"] = round(time.monotonic() - started, 1)
    return report


def _diagnose(issue, repo, llm, settings, research, report, notify, on_step):
    """Ask for a diagnosis; if the controller rejects it, research a bit more and retry."""
    if not repo.reads:
        return None, ["the agent did not read any code"]
    problems = []
    for attempt in range(settings.max_evidence_retries + 1):
        result = diag.ask_diagnosis(llm, issue, repo, previous_problems=problems)
        problems = diag.check(result, repo)
        if not problems:
            return result, []
        report["rejected_evidence"] += 1
        notify("diagnosis_rejected", problems)
        if attempt == settings.max_evidence_retries:
            break
        # Back to the research conversation for a few more steps, telling the
        # model exactly what the controller could not verify.
        research.messages.append({"role": "assistant", "content": result.model_dump_json()})
        run_research(issue, repo, llm, settings, on_step=on_step, research=research,
                     feedback=prompts.diagnosis_feedback(problems), max_steps=4)
    return None, problems
