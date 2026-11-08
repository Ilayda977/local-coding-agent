"""Phase 4: run_tests, the only "execute something" tool the agent has.

No shell, no free-form commands. The command is fixed:

    <this python> -m pytest -q --tb=line -rf -p no:cacheprovider [targets]

and targets may only be test files/node ids inside the repository. The model
cannot pass flags, pipes or other programs; there is nothing to inject into.
A timeout makes sure a hanging test cannot hang the agent.
"""
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field

from lca.tools import ToolError

FAILED_LINE = re.compile(r"^FAILED (.+?)(?: - .*)?$")
MAX_BRIEF_CHARS = 2500


@dataclass
class TestRun:
    passed: bool
    failed: list = field(default_factory=list)
    summary: str = ""
    brief: str = ""          # short failure description, safe to show the model
    timed_out: bool = False

    def as_dict(self):
        return asdict(self)


def validate_targets(repo, targets):
    """Allow only test files / node ids that live inside the repository."""
    clean = []
    for target in targets or []:
        path_part = str(target).split("::", 1)[0]
        if path_part.startswith("-"):
            raise ToolError(f"'{target}' looks like a command-line flag; only test paths are allowed")
        path = repo.resolve(path_part)
        name = path.name
        if not (path.is_dir() or name.startswith("test_") or name.endswith("_test.py")):
            raise ToolError(f"'{target}' is not a test file")
        clean.append(str(target))
    return clean


def run_tests(repo, targets=None, timeout=60):
    targets = validate_targets(repo, targets)
    # "-p no:anyio": a plugin pulled in by the ollama package prints an unrelated
    # warning on pytest 9; disabling a plugin that is not installed is harmless.
    command = [sys.executable, "-m", "pytest", "-q", "--tb=line", "-rf",
               "-p", "no:cacheprovider", "-p", "no:anyio", *targets]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        result = subprocess.run(command, cwd=repo.root, capture_output=True, text=True,
                                timeout=timeout, env=env)  # a list, never a shell string
    except subprocess.TimeoutExpired:
        return TestRun(passed=False, summary=f"tests timed out after {timeout} s",
                       brief=f"The test run took longer than {timeout} seconds and was stopped.",
                       timed_out=True)
    output = result.stdout.replace(str(repo.root) + os.sep, "")
    failed = [m.group(1) for line in output.splitlines() if (m := FAILED_LINE.match(line))]
    lines = [line for line in output.splitlines() if line.strip()]
    summary = lines[-1].strip("= ") if lines else "no output"
    # returncode 5 = "no tests collected"; anything above 1 means pytest itself failed.
    if result.returncode not in (0, 1):
        return TestRun(passed=False, summary=summary,
                       brief=(output + result.stderr)[-MAX_BRIEF_CHARS:])
    return TestRun(passed=result.returncode == 0, failed=failed, summary=summary,
                   brief=_brief(output) if failed else "")


def _brief(output):
    """Keep the useful part: one line per failure (file:line: error) + the FAILED list."""
    keep = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("=", "_", ".")) and set(stripped) <= set("=_. "):
            continue
        if "Warning" in stripped:
            continue  # warnings are noise for the model
        if re.match(r"^\S+\.py:\d+: ", stripped) or stripped.startswith("FAILED "):
            keep.append(stripped[:300])
    text = "\n".join(keep)
    return text[:MAX_BRIEF_CHARS]
