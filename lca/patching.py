"""Phase 3: plan -> diff -> human approval -> apply -> (rollback).

The model only *proposes* edits as ``old_text -> new_text`` pairs plus a short
plan. Everything that touches the disk happens here, after these checks:

* the file is inside the repository, exists, and the agent has read that code,
* test files are never edited (tests are the spec; "fixing" them is cheating),
* ``old_text`` is found exactly once (we tolerate indentation differences),
* the change is small (no whole-file rewrites, at most max_changed_lines),
* the result still parses as Python.

Nothing is written until ``approve(plan, diff)`` returns True. Before writing
we keep the original bytes, so ``rollback()`` can restore them exactly.
"""
import ast
import builtins
import difflib
import hashlib
import keyword
import os
import re
import tempfile
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from lca import prompts
from lca.tools import ToolError

PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {"type": "string", "maxLength": 600},
        "edits": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["file", "old_text", "new_text"],
            },
        },
    },
    "required": ["plan", "edits"],
}


class Edit(BaseModel):
    file: str
    old_text: str
    new_text: str


class PatchProposal(BaseModel):
    plan: str
    edits: list[Edit] = Field(default_factory=list)


class PatchError(Exception):
    """A proposed patch was rejected; the message goes back to the model."""


@dataclass
class FileChange:
    path: str          # repository-relative
    before: str
    after: str
    applied_hash: str = ""  # hash of what we wrote, to detect later manual edits


@dataclass
class PatchSet:
    """Validated changes, ready to apply (or already applied)."""
    repo_root: object
    plan: str
    changes: list = field(default_factory=list)
    applied: bool = False

    def diff(self):
        """Unified diff of all changes (this is the get_diff tool)."""
        chunks = []
        for change in self.changes:
            chunks.extend(difflib.unified_diff(
                change.before.splitlines(keepends=True), change.after.splitlines(keepends=True),
                fromfile=f"a/{change.path}", tofile=f"b/{change.path}"))
        return "".join(chunks)

    def changed_lines(self):
        return sum(1 for line in self.diff().splitlines()
                   if line[:1] in "+-" and not line.startswith(("+++", "---")))

    def apply(self):
        """Write every file atomically (temp file + rename): never half a file."""
        for change in self.changes:
            target = self.repo_root / change.path
            if _read(target) != change.before:
                raise PatchError(f"{change.path} changed on disk since it was read; not writing")
        for change in self.changes:
            _atomic_write(self.repo_root / change.path, change.after)
            change.applied_hash = _hash(change.after)
        self.applied = True

    def rollback(self):
        """Restore the original files, unless someone edited them after us."""
        if not self.applied:
            return []
        restored = []
        for change in self.changes:
            target = self.repo_root / change.path
            if _hash(_read(target)) != change.applied_hash:
                raise PatchError(f"{change.path} was modified after the patch; not rolling back")
            _atomic_write(target, change.before)
            restored.append(change.path)
        self.applied = False
        return restored


# ----------------------------------------------------------------------
# Asking the model
# ----------------------------------------------------------------------
def propose(llm, issue, diagnosis, repo, feedback=None, stage="patch"):
    """Ask the model for a plan + small edits. ``feedback`` explains a previous failure."""
    task = prompts.patch_task(issue, diagnosis, patch_context(repo, diagnosis), feedback)
    messages = [{"role": "system", "content": prompts.PATCH_SYSTEM},
                {"role": "user", "content": task}]
    return llm.chat_json(messages, PATCH_SCHEMA, stage, PatchProposal, num_predict=900)


def patch_context(repo, diagnosis, padding=6):
    """Current code around each evidence range, *without* line numbers.

    No numbers on purpose: the model must copy ``old_text`` exactly, and
    numbers in front of lines get copied by mistake.
    """
    blocks = []
    for ev in diagnosis["evidence"]:
        if is_test_file(ev["file"]):
            continue
        path = repo.root / ev["file"]
        if not path.is_file():
            continue
        lines = _read(path).splitlines()
        start, end = _enclosing_block(path, ev["start_line"], ev["end_line"])
        start, end = max(1, start - padding), min(len(lines), end + padding)
        body = "\n".join(lines[start - 1:end])
        # The model is shown these lines now, so it may edit them later
        # (this matters in repair rounds, after line numbers moved).
        repo.note_read(ev["file"], start, end)
        blocks.append(f"### {ev['file']} (lines {start}-{end})\n{body}")
    return "\n\n".join(dict.fromkeys(blocks)) or "(no source evidence outside tests)"


# ----------------------------------------------------------------------
# Validation: model proposal -> PatchSet (or PatchError)
# ----------------------------------------------------------------------
def build_patch(proposal, repo, max_changed_lines):
    if not proposal.edits:
        raise PatchError("the proposal contains no edits")
    contents = {}
    for edit in proposal.edits:
        try:
            path = repo.resolve(edit.file)
        except ToolError as error:
            raise PatchError(str(error)) from None
        rel = repo.relative(path)
        if is_test_file(rel):
            raise PatchError(f"{rel} is a test file; fix the code, not the tests")
        if not path.is_file():
            raise PatchError(f"{rel} does not exist; only existing files can be edited")
        if rel not in repo.read_files():
            raise PatchError(f"{rel} was never read; you may only edit code you have read")
        current = contents.get(rel, _read(path))
        updated, first_line, line_count = replace_once(current, edit.old_text, edit.new_text, rel)
        if not repo.was_read(rel, first_line, first_line + line_count - 1):
            raise PatchError(f"{rel}:{first_line}: those lines were never read")
        contents[rel] = updated

    unknown = invented_names(proposal, repo)
    if unknown:
        # Point at real names that look similar: "completed" -> completed_at.
        known = repo.known_names()
        hints = []
        for name in sorted(unknown):
            close = difflib.get_close_matches(name, known, n=3, cutoff=0.6)
            close += sorted(k for k in known if k.startswith(name) and k not in close)[:2]
            if close:
                hints.append(f"instead of '{name}' maybe: {', '.join(close)}")
        raise PatchError("the new code uses names that do not exist anywhere in the repository: "
                         + ", ".join(sorted(unknown)) + ". "
                         + ("; ".join(hints) + ". " if hints else "")
                         + "Use only existing fields/functions or remove that code.")

    changes = []
    for rel, after in contents.items():
        before = _read(repo.root / rel)
        if before == after:
            continue
        if rel.endswith(".py"):
            try:
                ast.parse(after)
            except SyntaxError as error:
                raise PatchError(f"{rel} would not be valid Python: {error.msg} "
                                 f"(line {error.lineno})") from None
        changes.append(FileChange(rel, before, after))
    if not changes:
        raise PatchError("the edits do not change anything")
    patch = PatchSet(repo.root, proposal.plan, changes)
    size = patch.changed_lines()
    if size > max_changed_lines:
        raise PatchError(f"patch changes {size} lines (limit {max_changed_lines}); "
                         "make a smaller, targeted change")
    for change in changes:
        total = len(change.before.splitlines())
        if total > 20 and size >= 0.8 * total:
            raise PatchError(f"{change.path}: rewriting the whole file is not allowed")
    return patch


def replace_once(content, old, new, label="file"):
    """Replace the single occurrence of ``old``; return (text, first_line, n_lines).

    1. exact match, if it occurs exactly once;
    2. otherwise compare line by line ignoring surrounding whitespace, and
       re-indent ``new`` to the indentation found in the file.
    The second step exists because small models often get indentation wrong
    when copying code, even when the code itself is right.
    """
    if not old.strip():
        raise PatchError(f"{label}: old_text is empty; copy the exact lines you want to change")
    count = content.count(old)
    if count == 1:
        offset = content.index(old)
        first = content.count("\n", 0, offset) + 1
        return content.replace(old, new, 1), first, max(1, old.count("\n") + 1)
    if count > 1:
        raise PatchError(f"{label}: old_text occurs {count} times; include more context")

    wanted = [line.strip() for line in old.strip("\n").splitlines()]
    lines = content.splitlines(keepends=True)
    hits = [i for i in range(len(lines) - len(wanted) + 1)
            if all(lines[i + j].strip() == wanted[j] for j in range(len(wanted)))]
    if len(hits) != 1:
        raise PatchError(f"{label}: old_text was not found " if not hits else
                         f"{label}: old_text matches {len(hits)} places; include more context")
    start = hits[0]
    actual_indent = _indent(lines[start])
    model_indent = _indent(next(l for l in old.splitlines() if l.strip()))
    rebuilt = []
    for line in new.strip("\n").splitlines():
        if not line.strip():
            rebuilt.append("\n")
        elif line.startswith(model_indent):
            rebuilt.append(actual_indent + line[len(model_indent):] + "\n")
        else:
            rebuilt.append(actual_indent + line.lstrip() + "\n")
    result = "".join(lines[:start] + rebuilt + lines[start + len(wanted):])
    return result, start + 1, len(wanted)


_STRING = re.compile(r"(\"\"\"[\s\S]*?\"\"\"|'\'\'[\s\S]*?'\'\'|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')")
_COMMENT = re.compile(r"#.*")
_NAME = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_PYTHON_NAMES = set(dir(builtins)) | set(keyword.kwlist) | {"self", "cls"}


def _code_names(text):
    text = _COMMENT.sub("", _STRING.sub('""', text))
    return set(_NAME.findall(text))


def invented_names(proposal, repo):
    """Names a patch introduces that exist nowhere in the repository's code."""
    introduced = set()
    for edit in proposal.edits:
        introduced |= _code_names(edit.new_text) - _code_names(edit.old_text)
    introduced -= _PYTHON_NAMES
    if not introduced:
        return set()
    return introduced - repo.known_names()


def is_test_file(rel):
    name = rel.rsplit("/", 1)[-1]
    return rel.startswith("tests/") or "/tests/" in rel or name.startswith("test_") \
        or name == "conftest.py"


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def _enclosing_block(path, start, end):
    """Smallest function containing the range (so the model sees whole logic)."""
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return start, end
    best = (start, end)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.lineno <= start and end <= node.end_lineno \
                and node.end_lineno - node.lineno < 60:
            if best == (start, end) or node.lineno > best[0]:
                best = (node.lineno, node.end_lineno)
    return best


def _indent(line):
    return line[: len(line) - len(line.lstrip())]


def _read(path):
    return path.read_text(encoding="utf-8")


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path, text):
    mode = path.stat().st_mode
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, mode & 0o777)
        os.replace(tmp, path)  # atomic on the same filesystem
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
