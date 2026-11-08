"""Phase 5: what the model sees each research step (context engineering).

Two ways to build the prompt:

1. **chat** (``compact_history=False``): the full conversation, every action and
   every observation, growing with each step. Simple, but by step 8 the model
   reads ~3000 tokens of its own history, re-reads files it already saw, and
   repeats its earlier (sometimes wrong) guesses.

2. **state** (``compact_history=True``): one fresh message per step with
   - the bug report and the repository map,
   - a one-line summary of every action taken so far,
   - all code read so far, merged per file (no duplicates),
   - the full result of only the latest action.

Same facts, less text, no stale chatter. The evaluation compares both.
"""
from lca import prompts


def summarize_step(step):
    """One line per past action. Code that was read lives in the code pack instead."""
    if step.status == "repeated":
        return f"{step.number}. {step.call} -> repeated, ignored"
    if step.status in {"error", "refused"}:
        return f"{step.number}. {step.call} -> {step.observation.splitlines()[0][:160]}"
    if step.call.startswith("read_file"):
        header = step.observation.splitlines()[0] if step.observation else ""
        return f"{step.number}. {step.call} -> read {header.rstrip(':')} (code below)"
    if step.call.startswith("finish"):
        return f"{step.number}. finish"
    lines = step.observation.splitlines()
    shown = "; ".join(line.strip() for line in lines[1:4])
    more = f" (+{len(lines) - 4} more)" if len(lines) > 4 else ""
    return f"{step.number}. {step.call} -> {lines[0] if lines else ''} {shown}{more}".strip()


def state_messages(issue, repo, research):
    """The compact prompt for the next research step."""
    parts = [prompts.research_task(issue, repo.repo_map())]
    if research.steps:
        parts.append("Actions so far:\n" + "\n".join(summarize_step(s) for s in research.steps))
    pack = repo.code_pack(max_chars=9000)
    if pack:
        parts.append("Code you have read so far (do not read these lines again):\n" + pack)
    for note in research.notes:
        parts.append(note)
    last = research.steps[-1] if research.steps else None
    if last and not last.call.startswith("read_file") and last.observation:
        parts.append(f"Latest result of {last.call}:\n{last.observation}")
    parts.append("Choose your next action (one tool) or finish.")
    return [{"role": "system", "content": prompts.RESEARCH_SYSTEM},
            {"role": "user", "content": "\n\n".join(parts)}]
