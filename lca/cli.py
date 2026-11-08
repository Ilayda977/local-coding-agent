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
    parser.add_argument("--fix", action="store_true",
                        help="after the diagnosis, propose a patch and apply it if you approve")
    parser.add_argument("--yes", action="store_true",
                        help="approve the patch without asking (only for throwaway copies!)")
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
        if kind == "patch_rejected":
            print("\n" + _style(BOLD, "Patch rejected by the controller: ", color) + data)
        if kind == "patch_applied":
            print("\n" + _style(BOLD, "Patch applied.", color))
        if kind == "tests":
            mark = "PASSED" if data.passed else "FAILED"
            print(_style(BOLD, f"run_tests: {mark}", color) + f"  {data.summary}")
            if data.brief:
                print(_style(DIM, "\n".join("    " + l for l in data.brief.splitlines()[:8]), color))
        if kind == "rolled_back":
            print(_style(BOLD, "Tests still fail after the repairs: changes rolled back.", color))
        if kind == "diagnosis_rejected":
            print("\n" + _style(BOLD, "Diagnosis rejected by the controller:", color))
            for problem in data:
                print(f"  - {problem}")

    def approve(plan, diff):
        """Human-in-the-loop: show plan + diff, write only after an explicit yes."""
        print("\n" + _style(BOLD, "== Proposed patch ==", color))
        print(f"plan: {plan}\n")
        print(_colored_diff(diff, color))
        if not sys.stdin.isatty():
            print("(no interactive terminal: patch NOT applied; use --yes on a throwaway copy)")
            return False
        answer = input("Apply this patch? Type 'yes' to apply: ").strip().lower()
        return answer == "yes"

    report = agent.run(args.issue, args.repo, settings, on_step=on_step, on_token=on_token,
                       events=on_event, fix=args.fix, auto_approve=args.yes,
                       approve=None if args.json else approve)

    if args.save:
        Path(args.save).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_summary(report, color)
    return 0 if report["status"] in {"diagnosed", "patched", "fixed"} else 1


def _colored_diff(diff, enabled):
    if not enabled:
        return diff
    out = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(f"\033[32m{line}{RESET}")
        elif line.startswith("-") and not line.startswith("---"):
            out.append(f"\033[31m{line}{RESET}")
        else:
            out.append(line)
    return "\n".join(out)


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
    patch = report.get("patch")
    if patch and patch.get("diff"):
        print("\n" + _style(BOLD, "== Final diff ==", color))
        print(_colored_diff(patch["diff"], color))
    print("\n" + _style(BOLD, "== Summary ==", color))
    print(f"status: {report['status']}  ({report.get('stop_reason', '')})")
    if report.get("tests"):
        print(f"tests: {'pass' if report['tests']['passed'] else 'fail'} after "
              f"{report['tests']['repairs']} repair round(s)")
    print(f"files read: {', '.join(report['files_read']) or '-'}")
    if report.get("error"):
        print(f"error: {report['error']}")
    print(f"model calls: {usage['model_calls']}, prompt tokens: {usage['prompt_tokens']} "
          f"(largest single prompt: {usage['max_prompt_tokens']}), time: {report['seconds']} s")


if __name__ == "__main__":
    sys.exit(main())
