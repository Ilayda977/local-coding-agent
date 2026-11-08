"""The pipeline: research -> diagnosis -> (plan + patch -> test -> repair).

This file only *orchestrates*. Each stage lives in its own module so it can be
understood and tested on its own. The result is a plain dict (RunReport) that
both the CLI and the evaluation script consume.
"""
import time
from pathlib import Path

from lca.llm import LLM, LLMError
from lca.research import run_research
from lca.tools import Repo


def run(issue, repo_path, settings, *, llm=None, on_step=None, on_token=None,
        auto_approve=False):
    """Investigate ``issue`` in ``repo_path`` and return a report dict."""
    started = time.monotonic()
    repo = Repo(Path(repo_path), max_read_lines=settings.max_read_lines,
                max_search_results=settings.max_search_results)
    llm = llm or LLM(settings, on_token=on_token)
    report = {
        "issue": issue,
        "model": settings.model,
        "repo": str(repo.root),
        "status": "started",
        "steps": [],
    }
    try:
        research = run_research(issue, repo, llm, settings, on_step=on_step)
        report["steps"] = [vars(step) for step in research.steps]
        report["research_finished"] = research.finished
        report["stop_reason"] = research.stop_reason
        report["status"] = "researched"
    except LLMError as error:
        report["status"] = "model_error"
        report["error"] = str(error)
    report["files_read"] = repo.read_files()
    report["blocked_paths"] = list(repo.blocked)
    report["usage"] = llm.usage()
    report["seconds"] = round(time.monotonic() - started, 1)
    return report
