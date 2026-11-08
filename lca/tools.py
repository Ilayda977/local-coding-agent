"""Read-only tools the model may use to explore a repository.

The golden rule of this file: the model *asks*, the tools *decide*.
Whatever path the model sends, we resolve it ourselves and refuse anything
that ends up outside the chosen repository (``../``, absolute paths,
symlinks pointing elsewhere). The model never touches the filesystem directly.

Every tool returns a short plain-text observation. Short matters: a 7B model
gets confused by walls of text, and every character costs context.
"""
import ast
import os
from dataclasses import dataclass, field
from pathlib import Path

# Folders that are never interesting for a code task and can be huge.
EXCLUDED_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules",
                 ".pytest_cache", ".mypy_cache", ".idea", ".vscode"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".ini", ".toml", ".cfg", ".json",
                 ".yaml", ".yml", ".js", ".ts", ".html", ".css", ".sh"}
MAX_FILE_BYTES = 512_000
MAX_LIST_ENTRIES = 200


class ToolError(Exception):
    """A tool call was refused or impossible. The message goes back to the model."""


@dataclass
class ReadRecord:
    path: str
    start: int
    end: int


@dataclass
class Repo:
    """One repository on disk plus a log of what the agent has read in it."""

    root: Path
    max_read_lines: int = 80
    max_search_results: int = 30
    reads: list = field(default_factory=list)
    blocked: list = field(default_factory=list)  # refused paths, for the evaluation report

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        if not self.root.is_dir():
            raise ToolError(f"repository folder does not exist: {self.root}")

    # ------------------------------------------------------------------
    # Safety: every path goes through here
    # ------------------------------------------------------------------
    def resolve(self, path):
        """Turn a model-provided path into a real path inside the repository."""
        text = str(path if path is not None else ".").strip() or "."
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        # resolve() also follows symlinks, so a link to /etc is caught as well.
        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            self.blocked.append(text)
            raise ToolError(f"'{text}' is outside the repository; only paths inside it are allowed")
        relative_parts = resolved.relative_to(self.root).parts
        if any(part in EXCLUDED_DIRS for part in relative_parts):
            self.blocked.append(text)
            raise ToolError(f"'{text}' is inside an ignored folder")
        return resolved

    def relative(self, path):
        return path.relative_to(self.root).as_posix() or "."

    def _iter_files(self, start):
        """All readable text files below ``start``, in a stable (sorted) order."""
        if start.is_file():
            yield start
            return
        for current, dirs, files in os.walk(start):
            # Editing ``dirs`` in place tells os.walk not to descend into them.
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith("."))
            for name in sorted(files):
                file = Path(current) / name
                if file.suffix not in TEXT_SUFFIXES or file.is_symlink():
                    continue
                if file.stat().st_size > MAX_FILE_BYTES:
                    continue
                yield file

    def _read_lines(self, file):
        try:
            return file.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            raise ToolError(f"{self.relative(file)} is not a UTF-8 text file") from None

    # ------------------------------------------------------------------
    # The four tools from the assignment
    # ------------------------------------------------------------------
    def list_files(self, path="."):
        start = self.resolve(path)
        if not start.exists():
            raise ToolError(f"'{path}' does not exist")
        files = [self.relative(f) for f in self._iter_files(start)]
        shown = files[:MAX_LIST_ENTRIES]
        header = f"{len(files)} files under '{self.relative(start)}'"
        if len(files) > len(shown):
            header += f" (showing first {len(shown)}; list a sub-folder to see more)"
        return header + ":\n" + "\n".join(shown)

    def search_code(self, query, path="."):
        """Case-insensitive text search. Returns ``file:line: code`` lines."""
        query = (query or "").strip()
        if not query:
            raise ToolError("search_code needs a non-empty 'query'")
        start = self.resolve(path)
        needle = query.lower()
        hits = []
        for file in self._iter_files(start):
            for number, line in enumerate(self._read_lines(file), start=1):
                if needle in line.lower():
                    hits.append(f"{self.relative(file)}:{number}: {line.strip()[:160]}")
        if not hits:
            hint = " Try one identifier (e.g. a function or variable name) instead of a sentence." \
                if " " in query else " Try a shorter or different name."
            return f"No matches for '{query}'.{hint}"
        shown = hits[: self.max_search_results]
        more = f" (showing first {len(shown)})" if len(hits) > len(shown) else ""
        return f"{len(hits)} matches for '{query}'{more}:\n" + "\n".join(shown)

    def find_symbol(self, name):
        """Find where a Python function, class, method or constant is *defined*."""
        name = (name or "").strip()
        if not name:
            raise ToolError("find_symbol needs a non-empty 'name'")
        wanted = name.split(".")[-1]  # "TaskService.is_overdue" -> "is_overdue"
        exact, similar = [], []
        for file in self._iter_files(self.root):
            if file.suffix != ".py":
                continue
            for qualified, kind, start, end in _definitions(file):
                location = f"{self.relative(file)}:{start}-{end}  {kind} {qualified}"
                short = qualified.split(".")[-1]
                if short == wanted and (name == wanted or qualified.endswith(name)):
                    exact.append(location)
                elif wanted.lower() in short.lower():
                    similar.append(location)
        if exact:
            return f"Definitions of '{name}':\n" + "\n".join(exact[: self.max_search_results])
        if similar:
            return (f"No exact definition of '{name}'. Similar names:\n"
                    + "\n".join(similar[:10]))
        return f"No definition of '{name}' found. Try search_code to find where it is used."

    def read_file(self, path, start_line=1, end_line=None):
        """Return numbered lines ``start_line..end_line`` (at most max_read_lines)."""
        file = self.resolve(path)
        if not file.is_file():
            raise ToolError(f"'{path}' is not a file; use list_files to see what exists")
        if file.suffix not in TEXT_SUFFIXES:
            raise ToolError(f"'{path}' is not a text/source file")
        lines = self._read_lines(file)
        total = len(lines)
        start = max(1, int(start_line or 1))
        if start > total:
            raise ToolError(f"{self.relative(file)} has only {total} lines")
        end = total if end_line in (None, "", 0) else min(int(end_line), total)
        if end < start:
            raise ToolError("end_line must be >= start_line")
        note = ""
        if end - start + 1 > self.max_read_lines:
            end = start + self.max_read_lines - 1
            note = (f"\n[showing {self.max_read_lines} lines; continue with "
                    f"start_line={end + 1} if you need more]")
        width = len(str(end))
        body = "\n".join(f"{n:>{width}} | {lines[n - 1]}" for n in range(start, end + 1))
        rel = self.relative(file)
        self.reads.append(ReadRecord(rel, start, end))
        return f"{rel} lines {start}-{end} of {total}:\n{body}{note}"

    # ------------------------------------------------------------------
    # Helpers used by the controller (not by the model)
    # ------------------------------------------------------------------
    def was_read(self, path, start, end):
        """True when every line in ``start..end`` was returned by read_file."""
        try:
            rel = self.relative(self.resolve(path))
        except ToolError:
            return False
        seen = set()
        for record in self.reads:
            if record.path == rel:
                seen.update(range(record.start, record.end + 1))
        return all(n in seen for n in range(start, end + 1))

    def read_files(self):
        """Files the agent has actually opened, in first-read order."""
        return list(dict.fromkeys(record.path for record in self.reads))


def _definitions(file):
    """Yield (qualified_name, kind, start_line, end_line) for a Python file."""
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return
    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                qualified = prefix + child.name
                yield qualified, kind, child.lineno, child.end_lineno
                if isinstance(child, ast.ClassDef):
                    yield from visit(child, qualified + ".")
            elif isinstance(child, (ast.Assign, ast.AnnAssign)) and not prefix:
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        yield target.id, "var", child.lineno, child.end_lineno
    yield from visit(tree, "")


# ----------------------------------------------------------------------
# Description of the tools, exactly as the model will see it.
# Clear, short descriptions are one of the cheapest ways to help a small model.
# ----------------------------------------------------------------------
TOOL_DOCS = """\
list_files(path=".")            -> every source file under a folder
search_code(query, path=".")    -> lines containing a word or identifier (case-insensitive)
find_symbol(name)               -> where a function/class/method/constant is defined (file:start-end)
read_file(path, start_line, end_line) -> numbered source lines, at most 80 per call
finish()                        -> stop researching; you have read the code that explains the issue"""

TOOL_NAMES = ["list_files", "search_code", "find_symbol", "read_file", "finish"]


def run_tool(repo, tool, args):
    """Dispatch one model action to the matching Repo method."""
    args = args or {}
    if tool == "list_files":
        return repo.list_files(args.get("path") or ".")
    if tool == "search_code":
        return repo.search_code(args.get("query") or args.get("name"), args.get("path") or ".")
    if tool == "find_symbol":
        return repo.find_symbol(args.get("name") or args.get("query"))
    if tool == "read_file":
        if not args.get("path"):
            raise ToolError("read_file needs 'path'")
        return repo.read_file(args["path"], args.get("start_line") or 1, args.get("end_line"))
    raise ToolError(f"unknown tool '{tool}'. Available: {', '.join(TOOL_NAMES)}")
