"""Tests for the read-only tools. No model involved: these must be 100% reliable."""
import os

import pytest

from lca.tools import Repo, ToolError, run_tool


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "project"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "service.py").write_text(
        "LIMIT = 3\n"
        "\n"
        "class Service:\n"
        "    def run(self, items):\n"
        "        return items[:LIMIT]\n"
        "\n"
        "def helper():\n"
        "    return 'Hello'\n"
    )
    (root / "long.py").write_text("\n".join(f"x{n} = {n}" for n in range(1, 201)) + "\n")
    (root / "venv").mkdir()
    (root / "venv" / "hidden.py").write_text("SECRET = 1\n")
    (tmp_path / "outside.py").write_text("OUTSIDE = True\n")
    return Repo(root)


# --- repository boundary -----------------------------------------------------

@pytest.mark.parametrize("path", ["../outside.py", "pkg/../../outside.py"])
def test_relative_escape_is_refused(repo, path):
    with pytest.raises(ToolError, match="outside the repository"):
        repo.read_file(path)
    assert repo.blocked  # recorded for the evaluation report


def test_absolute_path_outside_is_refused(repo, tmp_path):
    with pytest.raises(ToolError, match="outside"):
        repo.read_file(str(tmp_path / "outside.py"))


def test_absolute_path_inside_is_allowed(repo):
    assert "LIMIT = 3" in repo.read_file(str(repo.root / "pkg" / "service.py"))


def test_symlink_escape_is_refused(repo, tmp_path):
    os.symlink(tmp_path / "outside.py", repo.root / "link.py")
    with pytest.raises(ToolError, match="outside"):
        repo.read_file("link.py")


def test_ignored_folders_are_refused_and_not_listed(repo):
    with pytest.raises(ToolError, match="ignored"):
        repo.read_file("venv/hidden.py")
    assert "hidden.py" not in repo.list_files()


def test_missing_root_is_rejected(tmp_path):
    with pytest.raises(ToolError):
        Repo(tmp_path / "nope")


# --- list / search / symbols --------------------------------------------------

def test_list_files_is_sorted_and_recursive(repo):
    listing = repo.list_files()
    assert listing.splitlines()[1:] == ["long.py", "pkg/service.py"]


def test_search_code_reports_file_and_line(repo):
    result = repo.search_code("limit")
    assert "pkg/service.py:1: LIMIT = 3" in result
    assert "pkg/service.py:5 (in Service.run): return items[:LIMIT]" in result


def test_search_without_matches_gives_a_hint(repo):
    assert "Try one identifier" in repo.search_code("where is the limit set")


def test_search_needs_a_query(repo):
    with pytest.raises(ToolError):
        repo.search_code("  ")


def test_find_symbol_finds_methods_classes_and_constants(repo):
    assert "pkg/service.py:4-5  def Service.run" in repo.find_symbol("run")
    assert "pkg/service.py:4-5" in repo.find_symbol("Service.run")
    assert "pkg/service.py:3-5  class Service" in repo.find_symbol("Service")
    assert "pkg/service.py:1-1  var LIMIT" in repo.find_symbol("LIMIT")


def test_find_symbol_suggests_similar_names(repo):
    assert "Similar names" in repo.find_symbol("help")


# --- read_file ---------------------------------------------------------------------

def test_read_file_numbers_lines(repo):
    result = repo.read_file("pkg/service.py", 4, 5)
    assert "4 |     def run(self, items):" in result
    assert "5 |         return items[:LIMIT]" in result


def test_read_file_is_capped(repo):
    result = repo.read_file("long.py", 1, 200)
    assert "lines 1-80 of 200" in result
    assert "start_line=81" in result
    assert "x81" not in result


def test_read_file_past_the_end(repo):
    with pytest.raises(ToolError, match="only 200 lines"):
        repo.read_file("long.py", 500, 510)


def test_read_log_tracks_exact_ranges(repo):
    repo.min_read_lines = 1  # no widening, so we can check exact ranges
    repo.read_file("pkg/service.py", 1, 4)
    assert repo.was_read("pkg/service.py", 3, 4)
    assert not repo.was_read("pkg/service.py", 3, 6)
    repo.read_file("pkg/service.py", 5, 8)
    assert repo.was_read("pkg/service.py", 1, 8)
    assert repo.read_files() == ["pkg/service.py"]


def test_run_tool_rejects_unknown_tools(repo):
    with pytest.raises(ToolError, match="unknown tool"):
        run_tool(repo, "delete_everything", {})


def test_run_tool_tolerates_swapped_argument_names(repo):
    # Small models sometimes send {"query": ...} to find_symbol; be forgiving.
    assert "Service.run" in run_tool(repo, "find_symbol", {"query": "run"})


def test_search_names_the_enclosing_function(repo):
    assert "pkg/service.py:5 (in Service.run): return items[:LIMIT]" in repo.search_code("items[")


def test_repo_map_lists_definitions_per_file(repo):
    text = repo.repo_map()
    assert "pkg/service.py: LIMIT, class Service(run), helper" in text
    assert "SECRET" not in text  # ignored folders stay out


def test_relevant_args_drops_noise_and_fixes_swapped_names():
    from lca.tools import relevant_args
    assert relevant_args("search_code", {"query": "x", "start_line": 1, "end_line": None}) == {"query": "x"}
    assert relevant_args("search_code", {"name": "x"}) == {"query": "x"}
    assert relevant_args("finish", {"path": "a.py"}) == {}


def test_tiny_reads_are_widened_to_the_enclosing_function(tmp_path):
    body = ["X = 1", ""] + [f"# filler {n}" for n in range(30)] + [
        "def target(a):", "    b = a + X", "    c = b * 2", "    d = c - 1", "    return d", ""]
    (tmp_path / "m.py").write_text("\n".join(body) + "\n")
    repo = Repo(tmp_path, min_read_lines=3)
    result = repo.read_file("m.py", 35, 35)
    assert "lines 33-37" in result and "widened from 35-35" in result


def test_read_shows_related_definitions_and_uses(repo):
    repo.min_read_lines = 1
    result = repo.read_file("pkg/service.py", 4, 5)
    assert "Defined elsewhere in this file: LIMIT (lines 1-1)" in result
    result = repo.read_file("pkg/service.py", 1, 1)
    assert "Used elsewhere in this file: LIMIT at line 5 (in Service.run)" in result


def test_code_pack_merges_reads_per_file(repo):
    repo.min_read_lines = 1
    repo.read_file("pkg/service.py", 1, 1)
    repo.read_file("pkg/service.py", 4, 5)
    repo.read_file("pkg/service.py", 5, 5)  # duplicate line appears once
    pack = repo.code_pack()
    assert pack.splitlines() == ["### pkg/service.py", "1 | LIMIT = 3", "   ...",
                                 "4 |     def run(self, items):", "5 |         return items[:LIMIT]"]
