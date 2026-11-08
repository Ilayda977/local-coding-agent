"""Evaluation issue set: create buggy workspaces and verify the dataset.

Each issue in ``eval/issues/*.json`` describes ONE bug as a text replacement
(``bug.find`` -> ``bug.replace``) applied to a clean copy of ``taskflow/``.
The agent only ever sees that copy; the JSON (with the ground truth) stays here.

    python eval/issues.py list
    python eval/issues.py check              # clean repo green, every bug breaks exactly its tests
    python eval/issues.py prepare easy_01    # -> eval/workspace/easy_01
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKFLOW = ROOT / "taskflow"
ISSUES_DIR = ROOT / "eval" / "issues"
WORKSPACE_DIR = ROOT / "eval" / "workspace"
IGNORED = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc")
# Test ids may contain spaces (e.g. "[a li@example.com]"); pytest appends " - <message>".
FAILED_LINE = re.compile(r"^FAILED (.+?)(?: - .*)?$")


def load_issues():
    issues = [json.loads(path.read_text()) for path in sorted(ISSUES_DIR.glob("*.json"))]
    for issue, path in zip(issues, sorted(ISSUES_DIR.glob("*.json"))):
        if issue["id"] != path.stem:
            raise ValueError(f"{path.name}: id must match the file name")
    return issues


def get_issue(issue_id):
    for issue in load_issues():
        if issue["id"] == issue_id:
            return issue
    raise SystemExit(f"unknown issue: {issue_id}")


def bug_parts(issue):
    """An issue's bug is one replacement or a list of them (multi-file bugs)."""
    bug = issue["bug"]
    return bug if isinstance(bug, list) else [bug]


def apply_bug(workspace, bug):
    """Inject the bug; every 'find' text must occur exactly once."""
    for part in (bug if isinstance(bug, list) else [bug]):
        target = workspace / part["file"]
        source = target.read_text()
        count = source.count(part["find"])
        if count != 1:
            raise ValueError(f"{part['file']}: bug text found {count} times, expected 1")
        target.write_text(source.replace(part["find"], part["replace"]))


def prepare(issue, dest=None):
    """Copy the clean repo to ``dest`` and inject the issue's bug."""
    dest = Path(dest) if dest else WORKSPACE_DIR / issue["id"]
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(TASKFLOW, dest, ignore=IGNORED)
    apply_bug(dest, issue["bug"])
    return dest


def failing_tests(repo):
    """Run pytest in ``repo`` and return the set of failing test ids."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider"],
        cwd=repo, capture_output=True, text=True, timeout=120,
    )
    failed = {m.group(1) for line in result.stdout.splitlines()
              if (m := FAILED_LINE.match(line))}
    if result.returncode not in (0, 1) or (result.returncode == 1 and not failed):
        raise RuntimeError(f"pytest could not run in {repo}:\n{result.stdout}\n{result.stderr}")
    return failed


def check():
    ok = True
    clean = failing_tests(TASKFLOW)
    print(f"clean taskflow: {'OK, all tests pass' if not clean else f'FAILING {sorted(clean)}'}")
    ok &= not clean
    for issue in load_issues():
        workspace = prepare(issue)
        actual = failing_tests(workspace)
        expected = set(issue["failing_tests"])
        good = actual == expected
        ok &= good
        print(f"{issue['id']}: {'OK' if good else 'MISMATCH'} ({len(actual)} failing) - {issue['title_tr']}")
        if not good:
            print(f"    expected: {sorted(expected)}\n    actual:   {sorted(actual)}")
        shutil.rmtree(workspace)
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    prep = sub.add_parser("prepare")
    prep.add_argument("issue_id")
    prep.add_argument("--dest")
    args = parser.parse_args(argv)

    if args.command == "list":
        for issue in load_issues():
            print(f"{issue['id']}  [{issue['difficulty']}]  {issue['title_tr']}")
    elif args.command == "check":
        return 0 if check() else 1
    elif args.command == "prepare":
        print(prepare(get_issue(args.issue_id), args.dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
