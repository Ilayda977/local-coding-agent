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
import re
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
    min_read_lines: int = 20
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
        """Case-insensitive text search. Returns ``file:line (in function): code`` lines.

        Naming the enclosing function was a fix after our first live run: the
        model found the right line but did not know what to read next.
        """
        query = (query or "").strip()
        if not query:
            raise ToolError("search_code needs a non-empty 'query'")
        start = self.resolve(path)
        needle = query.lower()
        hits = []
        for file in self._iter_files(start):
            spans = list(_definitions(file)) if file.suffix == ".py" else []
            for number, line in enumerate(self._read_lines(file), start=1):
                if needle in line.lower():
                    owner = _enclosing(spans, number)
                    where = f" (in {owner})" if owner else ""
                    hits.append(f"{self.relative(file)}:{number}{where}: {line.strip()[:140]}")
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
            return (f"Definitions of '{name}':\n" + "\n".join(exact[: self.max_search_results])
                    + "\nNext: read_file with that path and line range.")
        if similar:
            return (f"No exact definition of '{name}'. Similar names:\n"
                    + "\n".join(similar[:10]))
        return (f"No definition of '{name}' found (it may be an attribute or field). "
                "Use search_code to find where it is used.")

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
        spans = list(_definitions(file)) if file.suffix == ".py" else []
        note = ""
        if end - start + 1 < self.min_read_lines:
            # Live runs showed the model reading 5-line slices and missing the
            # line right above. Widen tiny reads to the whole enclosing function
            # (or at least min_read_lines), so one read gives enough context.
            requested = (start, end)
            start, end = self._widen(spans, start, end, total)
            if (start, end) != requested:
                note += f"\n[widened from {requested[0]}-{requested[1]} to give context]"
        if end - start + 1 > self.max_read_lines:
            end = start + self.max_read_lines - 1
            note += (f"\n[showing {self.max_read_lines} lines; continue with "
                     f"start_line={end + 1} if you need more]")
        width = len(str(end))
        body = "\n".join(f"{n:>{width}} | {lines[n - 1]}" for n in range(start, end + 1))
        rel = self.relative(file)
        self.reads.append(ReadRecord(rel, start, end))
        hints = _related_hints(spans, lines, start, end)
        return f"{rel} lines {start}-{end} of {total}:\n{body}{note}{hints}"

    def _widen(self, spans, start, end, total):
        """Smallest enclosing function/method that fits, else pad around the request."""
        enclosing = [(s, e) for _q, kind, s, e in spans
                     if kind == "def" and s <= start and end <= e and e - s < self.max_read_lines]
        if enclosing:
            start, end = max(enclosing)  # innermost = latest start
        if end - start + 1 < self.min_read_lines:
            missing = self.min_read_lines - (end - start + 1)
            start = max(1, start - missing // 2)
            end = min(total, start + self.min_read_lines - 1)
        return start, end

    def repo_map(self, max_chars=3000):
        """A compact table of contents: each file with the names it defines.

        This is the "repo map" idea from the assignment's troubleshooting table.
        It costs a few hundred tokens and tells the model where things live
        without loading any code.
        """
        lines = []
        for file in self._iter_files(self.root):
            rel = self.relative(file)
            if file.suffix != ".py" or file.name == "__init__.py" and not file.stat().st_size:
                continue  # empty __init__ files and configs tell the model nothing
            if rel.startswith("tests/") or "/tests/" in rel:
                lines.append(rel)  # test names are long and noisy; the file name is enough
                continue
            lines.append(f"{rel}: {_outline(file)}" if _outline(file) else rel)
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[... map cut; use list_files for the rest]"
        return text

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

    def note_read(self, path, start, end):
        """Record lines the controller showed the model outside read_file."""
        self.reads.append(ReadRecord(path, start, end))

    def read_files(self):
        """Files the agent has actually opened, in first-read order."""
        return list(dict.fromkeys(record.path for record in self.reads))

    def code_pack(self, max_chars=12000):
        """Everything the agent has read, merged per file, with real line numbers.

        The diagnosis step gets this instead of the whole research chat: the
        same facts, without the model's earlier guesses (which it tends to
        repeat even when they were wrong) and without duplicated reads.
        """
        blocks = []
        for rel in self.read_files():
            lines_read = set()
            for record in self.reads:
                if record.path == rel:
                    lines_read.update(range(record.start, record.end + 1))
            source = self._read_lines(self.root / rel)
            numbers = sorted(n for n in lines_read if n <= len(source))
            width = len(str(numbers[-1])) if numbers else 1
            out, previous = [f"### {rel}"], None
            for n in numbers:
                if previous is not None and n != previous + 1:
                    out.append("   ...")
                out.append(f"{n:>{width}} | {source[n - 1]}")
                previous = n
            blocks.append("\n".join(out))
        text = "\n\n".join(blocks)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[... more code was read but is cut here]"
        return text

    def known_names(self):
        """Every name used in the repository's Python *code* (not strings/comments).

        Variables, attributes, functions, classes, arguments, imports. Used to
        catch patches that invent things like ``task.completed`` when the real
        field is ``task.completed_at``.
        """
        names = set()
        for file in self._iter_files(self.root):
            if file.suffix != ".py":
                continue
            try:
                tree = ast.parse(file.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.arg):
                    names.add(node.arg)
                elif isinstance(node, ast.keyword) and node.arg:
                    names.add(node.arg)
                elif isinstance(node, ast.alias):
                    names.add((node.asname or node.name).split(".")[0])
        return names

    def contains_identifier(self, name):
        """Does ``name`` appear as a whole word anywhere in the repository's code?

        Used to catch invented function/variable names in a diagnosis. We do not
        cache: files may change between calls (e.g. after a patch).
        """
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        for file in self._iter_files(self.root):
            try:
                if pattern.search(file.read_text(encoding="utf-8")):
                    return True
            except UnicodeDecodeError:
                continue
        return False


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


def _related_hints(spans, lines, start, end, limit=5):
    """Point at code just outside the read range that the range depends on.

    * "defined elsewhere": module-level names used in the range but defined
      on other lines of this file (e.g. a constant table above a function);
    * "used elsewhere": names defined in the range and used on other lines.

    A small, general nudge toward the next useful read; it is not an answer.
    """
    top_level = {q: (s, e) for q, kind, s, e in spans if "." not in q}
    if not top_level:
        return ""
    text = "\n".join(lines[start - 1:end])
    used_here = set(_WORD.findall(text))
    defined_elsewhere = []
    for name, (s, e) in top_level.items():
        if name in used_here and (e < start or s > end):
            defined_elsewhere.append(f"{name} (lines {s}-{e})")
    used_elsewhere = []
    for name, (s, e) in top_level.items():
        if not (start <= s and e <= end):
            continue
        for number, line in enumerate(lines, start=1):
            if (number < start or number > end) and name in _WORD.findall(line):
                owner = _enclosing(spans, number)
                used_elsewhere.append(f"{name} at line {number}" + (f" (in {owner})" if owner else ""))
    parts = []
    if defined_elsewhere:
        parts.append("Defined elsewhere in this file: " + ", ".join(defined_elsewhere[:limit]))
    if used_elsewhere:
        parts.append("Used elsewhere in this file: " + ", ".join(used_elsewhere[:limit]))
    return ("\n[" + "; ".join(parts) + "]") if parts else ""


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _outline(file):
    """'class TaskService(create, assign), paginate, MAX_PER_PAGE' for one file."""
    classes, items = {}, []
    for qualified, kind, _start, _end in _definitions(file):
        parts = qualified.split(".")
        if kind == "class" and len(parts) == 1:
            classes[qualified] = []
            items.append(qualified)
        elif len(parts) == 2 and parts[0] in classes and not parts[1].startswith("__"):
            classes[parts[0]].append(parts[1])
        elif len(parts) == 1 and kind == "def":
            items.append(qualified)
        elif len(parts) == 1 and kind == "var" and qualified.isupper():
            items.append(qualified)  # constants such as ALLOWED_TRANSITIONS
    rendered = []
    for item in items:
        if item in classes:
            methods = classes[item]
            rendered.append(f"class {item}({', '.join(methods)})" if methods else f"class {item}")
        else:
            rendered.append(item)
    return ", ".join(rendered)


def _enclosing(spans, line):
    """Name of the innermost function/class whose lines contain ``line``."""
    best = None
    for qualified, kind, start, end in spans:
        if kind != "var" and start <= line <= end:
            if best is None or start >= best[1]:
                best = (qualified, start)
    return best[0] if best else None


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


TOOL_ARGS = {
    "list_files": ("path",),
    "search_code": ("query", "path"),
    "find_symbol": ("name",),
    "read_file": ("path", "start_line", "end_line"),
    "finish": (),
}


def relevant_args(tool, args):
    """Drop arguments a tool does not use (models like to add start_line to searches)."""
    args = args or {}
    if tool == "search_code" and not args.get("query") and args.get("name"):
        args = {**args, "query": args["name"]}
    if tool == "find_symbol" and not args.get("name") and args.get("query"):
        args = {**args, "name": args["query"]}
    return {k: args[k] for k in TOOL_ARGS.get(tool, ()) if args.get(k) not in (None, "")}


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
