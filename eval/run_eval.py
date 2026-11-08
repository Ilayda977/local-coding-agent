"""Run the agent on the issue set and measure where it succeeds or breaks.

    python eval/run_eval.py                       # all issues, default model
    python eval/run_eval.py --issues easy_01 easy_02 --model qwen2.5-coder:3b
    python eval/run_eval.py --name before_compaction --set compact_history=false

Every issue starts from a fresh, clean copy of taskflow with only that issue's
bug injected (see eval/issues.py), so runs never influence each other.
Results go to eval/results/<name>.json and a readable eval/results/<name>.md.
"""
import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import issues as issue_set  # noqa: E402  (eval/issues.py)
from lca import agent  # noqa: E402
from lca.config import load_settings  # noqa: E402
from lca.llm import LLM  # noqa: E402
from metrics import score  # noqa: E402

RESULTS = ROOT / "eval" / "results"


def parse_overrides(pairs):
    overrides = {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        overrides[key] = value
    return overrides


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate the agent on eval/issues")
    parser.add_argument("--issues", nargs="*", help="issue ids (default: all)")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    parser.add_argument("--model")
    parser.add_argument("--name", help="result file name (default: model + time)")
    parser.add_argument("--set", nargs="*", metavar="KEY=VALUE", help="override Settings fields")
    parser.add_argument("--rescore", metavar="NAME",
                        help="recompute metrics of a saved run (no model calls)")
    args = parser.parse_args(argv)
    if args.rescore:
        return rescore(args.rescore)

    settings = load_settings(model=args.model)
    if args.set:
        from lca.config import Settings, _convert
        from dataclasses import replace
        defaults = Settings()
        settings = replace(settings, **{k: _convert(v, getattr(defaults, k))
                                        for k, v in parse_overrides(args.set).items()})
    selected = [i for i in issue_set.load_issues()
                if (not args.issues or i["id"] in args.issues)
                and (not args.difficulty or i["difficulty"] == args.difficulty)]
    name = args.name or f"{settings.model.replace(':', '-')}_{time.strftime('%Y%m%d-%H%M%S')}"

    print(f"Warming up {settings.model} ...", flush=True)
    LLM(settings).warm_up()  # first load is slow; do not count it against issue 1

    rows = []
    for issue in selected:
        workspace = issue_set.prepare(issue)
        print(f"\n=== {issue['id']}: {issue['title_tr']}", flush=True)
        report = agent.run(issue["issue"], workspace, settings, auto_approve=True,
                           on_step=lambda s: print(f"  [{s.number}] {s.call} ({s.status})", flush=True))
        row = score(issue, report, workspace)
        rows.append({"issue": issue["id"], "difficulty": issue["difficulty"],
                     "title": issue["title_tr"], "metrics": row, "report": report})
        print("  -> " + ", ".join(f"{k}={v}" for k, v in row.items()), flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "settings": asdict(settings), "results": rows}
    (RESULTS / f"{name}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (RESULTS / f"{name}.md").write_text(render_markdown(payload))
    print(f"\nSaved eval/results/{name}.md")
    print(render_markdown(payload))


def rescore(name):
    """Re-apply eval/metrics.py to stored reports (e.g. after improving a metric)."""
    path = RESULTS / f"{name}.json"
    payload = json.loads(path.read_text())
    issues_by_id = {i["id"]: i for i in issue_set.load_issues()}
    for row in payload["results"]:
        issue = issues_by_id[row["issue"]]
        workspace = issue_set.prepare(issue)  # same bug -> same line numbers
        row["metrics"] = score(issue, row["report"], workspace)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (RESULTS / f"{name}.md").write_text(render_markdown(payload))
    print(render_markdown(payload))


COLUMNS = ["retrieval", "diagnosis", "valid_patch", "tests_pass", "autonomous",
           "steps", "prompt_tokens", "seconds", "unsafe_or_invalid"]


def render_markdown(payload):
    rows = payload["results"]
    lines = [f"# Evaluation: {payload['name']}", "",
             f"Model: `{payload['settings']['model']}` | compact_history: "
             f"{payload['settings']['compact_history']}", "",
             "| issue | " + " | ".join(COLUMNS) + " |",
             "|---|" + "---|" * len(COLUMNS)]
    for row in rows:
        m = row["metrics"]
        cells = [_cell(m.get(c)) for c in COLUMNS]
        lines.append(f"| {row['issue']} | " + " | ".join(cells) + " |")
    if rows:
        totals = []
        for c in COLUMNS:
            values = [r["metrics"].get(c) for r in rows]
            if all(v is None for v in values):
                totals.append("–")  # not measured in this run
            elif all(isinstance(v, bool) or v is None for v in values):
                totals.append(f"{sum(1 for v in values if v)}/{len(values)}")
            else:
                nums = [v for v in values if isinstance(v, (int, float))]
                totals.append(f"avg {sum(nums) / len(nums):.0f}" if nums else "-")
        lines.append("| **total** | " + " | ".join(totals) + " |")
    return "\n".join(lines) + "\n"


def _cell(value):
    if value is True:
        return "✅"
    if value is False:
        return "❌"
    if value is None:
        return "–"
    return str(value)


if __name__ == "__main__":
    main()
