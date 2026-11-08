"""The pipeline: research -> diagnosis -> plan + patch -> approval -> apply.

This file only *orchestrates*. Each stage lives in its own module so it can be
understood and tested on its own. The result is a plain dict (the "report")
that both the CLI and the evaluation script consume.

Status values a report can end with:
  diagnosed              grounded diagnosis, no fix requested
  insufficient_evidence  the agent could not back its explanation with code it read
  patch_unavailable      no valid patch after the allowed attempts
  patch_not_approved     a valid patch was shown, but the human said no
  patched                the approved patch was applied
  model_error            the model kept producing invalid output / was unreachable
"""
import time
from pathlib import Path

from lca import diagnosis as diag
from lca import patching, prompts
from lca.llm import LLM, LLMError
from lca.research import run_research
from lca.tools import Repo

PATCH_ATTEMPTS = 2  # one proposal + one corrected proposal after controller feedback


def run(issue, repo_path, settings, *, llm=None, on_step=None, on_token=None,
        fix=False, auto_approve=False, approve=None, events=None):
    """Investigate ``issue`` in ``repo_path`` and return a report dict.

    fix          also plan and apply a patch after a successful diagnosis
    approve      callback ``approve(plan, diff) -> bool`` asked before writing
    auto_approve skip the question (the evaluation does this on throwaway copies)
    events       optional callback ``events(kind, data)`` for progress messages
    """
    started = time.monotonic()
    notify = events or (lambda kind, data: None)
    repo = Repo(Path(repo_path), max_read_lines=settings.max_read_lines,
                max_search_results=settings.max_search_results,
                min_read_lines=settings.min_read_lines)
    llm = llm or LLM(settings, on_token=on_token)
    report = {"issue": issue, "model": settings.model, "repo": str(repo.root),
              "status": "started", "steps": [], "rejected_evidence": 0}
    research = None
    try:
        research = run_research(issue, repo, llm, settings, on_step=on_step)
        result, problems = _diagnose(issue, repo, llm, settings, research, report, notify,
                                     on_step)
        report["stop_reason"] = research.stop_reason
        if result is None:
            report["status"] = "insufficient_evidence"
            report["diagnosis_problems"] = problems
        else:
            report["status"] = "diagnosed"
            report["diagnosis"] = result.model_dump()
            if fix:
                _fix(issue, repo, llm, settings, report, notify, auto_approve, approve)
    except LLMError as error:
        report["status"] = "model_error"
        report["error"] = str(error)
    if research is not None:
        report["steps"] = [vars(step) for step in research.steps]
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


def _make_patch(issue, repo, llm, settings, diagnosis, notify, feedback=None, stage="patch"):
    """Ask for a patch; on a controller rejection, explain why and ask once more."""
    rejected = []
    for _ in range(PATCH_ATTEMPTS):
        proposal = patching.propose(llm, issue, diagnosis, repo, feedback=feedback, stage=stage)
        try:
            return patching.build_patch(proposal, repo, settings.max_changed_lines), rejected
        except patching.PatchError as error:
            rejected.append(str(error))
            notify("patch_rejected", str(error))
            feedback = (f"Your previous patch was rejected: {error}\n"
                        "Copy old_text exactly from the current code and keep the change small.")
    return None, rejected


def _fix(issue, repo, llm, settings, report, notify, auto_approve, approve):
    diagnosis = report["diagnosis"]
    patch, rejected = _make_patch(issue, repo, llm, settings, diagnosis, notify)
    report["patch"] = {"rejected": len(rejected), "rejections": rejected, "applied": False}
    if patch is None:
        report["status"] = "patch_unavailable"
        return
    report["patch"].update(plan=patch.plan, diff=patch.diff(),
                           changed_lines=patch.changed_lines())
    # Human in the loop: nothing is written without a yes.
    if not (auto_approve or (approve is not None and approve(patch.plan, patch.diff()))):
        report["status"] = "patch_not_approved"
        return
    patch.apply()
    report["patch"]["applied"] = True
    report["status"] = "patched"
    notify("patch_applied", patch.diff())
