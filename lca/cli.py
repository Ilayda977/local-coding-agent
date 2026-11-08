"""Command line interface: `python -m lca --repo PATH "bug report"`."""
import argparse
import json
import sys
from pathlib import Path

from lca import agent
from lca.config import load_settings

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


def _style(code, text, enabled):
    return f"{code}{text}{RESET}" if enabled else text


def build_parser():
    parser = argparse.ArgumentParser(prog="lca", description="Local coding agent (Ollama)")
    parser.add_argument("issue", help="bug report / issue text")
    parser.add_argument("--repo", required=True, help="repository folder the agent may read")
    parser.add_argument("--model", help="Ollama model (default: qwen2.5-coder:7b)")
    parser.add_argument("--json", action="store_true", help="print only the final JSON report")
    parser.add_argument("--save", metavar="FILE", help="also write the JSON report to FILE")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    settings = load_settings(model=args.model)
    color = sys.stdout.isatty() and not args.json

    def on_token(text):
        # Streaming: show the model's reply as it is generated.
        if not args.json:
            print(_style(DIM, text, color), end="", flush=True)

    def on_step(step):
        if args.json:
            return
        print()
        print(_style(BOLD, f"[{step.number}] {step.call}", color) + f"  ({step.status})")
        if step.observation:
            preview = step.observation.splitlines()
            shown = "\n".join("    " + line for line in preview[:6])
            more = f"\n    ... ({len(preview) - 6} more lines)" if len(preview) > 6 else ""
            print(_style(DIM, shown + more, color))

    if not args.json:
        print(f"Model: {settings.model} | repo: {Path(args.repo).resolve()}")
    def on_event(kind, data):
        if args.json:
            return
        if kind == "diagnosis_rejected":
            print("\n" + _style(BOLD, "Diagnosis rejected by the controller:", color))
            for problem in data:
                print(f"  - {problem}")

    report = agent.run(args.issue, args.repo, settings, on_step=on_step, on_token=on_token,
                       events=on_event)

    if args.save:
        Path(args.save).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_summary(report, color)
    return 0 if report["status"] not in {"model_error"} else 1


def _print_summary(report, color):
    usage = report["usage"]
    diagnosis = report.get("diagnosis")
    if diagnosis:
        print("\n" + _style(BOLD, "== Diagnosis ==", color))
        print(f"issue: {diagnosis['issue_summary']}")
        print(f"root cause: {diagnosis['root_cause']}")
        print(f"files: {', '.join(diagnosis['relevant_files'])}")
        for ev in diagnosis["evidence"]:
            print(f"- {ev['file']}:{ev['start_line']}-{ev['end_line']}  {ev['why']}")
            # This code comes from disk (controller), not from the model.
            print(_style(DIM, "\n".join("    " + line for line in ev["code"].splitlines()), color))
        print(f"confidence (model's own guess, not a probability): {diagnosis['confidence']}")
    for problem in report.get("diagnosis_problems", []):
        print(f"! {problem}")
    print("\n" + _style(BOLD, "== Summary ==", color))
    print(f"status: {report['status']}  ({report.get('stop_reason', '')})")
    print(f"files read: {', '.join(report['files_read']) or '-'}")
    if report.get("error"):
        print(f"error: {report['error']}")
    print(f"model calls: {usage['model_calls']}, prompt tokens: {usage['prompt_tokens']}, "
          f"time: {report['seconds']} s")


if __name__ == "__main__":
    sys.exit(main())
