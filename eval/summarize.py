"""Compare evaluation runs and classify failures (failure taxonomy).

    python eval/summarize.py final_7b final_3b step7_chat_7b

For every run: totals per difficulty, and for every unsolved issue the *first*
stage where it broke. "First" matters: a wrong patch after a wrong diagnosis
is a diagnosis problem, not a patching problem.
"""
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
BOOLEAN = ["retrieval", "diagnosis", "valid_patch", "tests_pass", "autonomous"]


def failure_class(row):
    """The first pipeline stage that failed for this issue."""
    report, metrics = row["report"], row["metrics"]
    status = report.get("status")
    if metrics.get("autonomous"):
        return None
    if status in {"model_error", "crashed"}:
        return "F0 format/budget: model output unusable or call budget used up"
    if not metrics.get("retrieval"):
        return "F1 localization: never read the buggy file"
    if status == "insufficient_evidence":
        return "F2 grounding: diagnosis cited code it had not read"
    if not metrics.get("diagnosis"):
        if metrics.get("tests_pass"):
            return None  # solved anyway (e.g. repaired from test feedback)
        return "F3 misdiagnosis: read the right code, explained it wrong"
    if status == "patch_unavailable":
        return "F4 patch generation: no patch passed the controller checks"
    return "F5 wrong fix: patch applied, tests still fail after repairs"


def summarize(name):
    payload = json.loads((RESULTS / f"{name}.json").read_text())
    rows = payload["results"]
    print(f"\n## {name} ({payload['settings']['model']}, compact_history="
          f"{payload['settings']['compact_history']})\n")
    print("| difficulty | n | " + " | ".join(BOOLEAN) + " | avg prompt tokens | avg max prompt | avg seconds |")
    print("|---|---|" + "---|" * (len(BOOLEAN) + 3))
    for level in ["easy", "medium", "hard", "all"]:
        group = [r for r in rows if level == "all" or r["difficulty"] == level]
        if not group:
            continue
        cells = [f"{sum(1 for r in group if r['metrics'].get(m))}/{len(group)}" for m in BOOLEAN]
        avg = lambda key: sum(r["metrics"].get(key, 0) or 0 for r in group) / len(group)
        max_prompt = sum(r["report"].get("usage", {}).get("max_prompt_tokens", 0)
                         for r in group) / len(group)
        print(f"| {level} | {len(group)} | " + " | ".join(cells) +
              f" | {avg('prompt_tokens'):.0f} | {max_prompt:.0f} | {avg('seconds'):.0f} |")
    print("\nFailures (first broken stage):")
    for row in rows:
        reason = failure_class(row)
        if reason:
            print(f"- {row['issue']}: {reason}")


if __name__ == "__main__":
    for run in sys.argv[1:]:
        summarize(run)
