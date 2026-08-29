import unittest

import tools


class ReadOnlyToolTests(unittest.TestCase):
    def test_project_root_is_based_on_tools_file(self):
        self.assertEqual(tools.PROJECT_ROOT.name, "local-coding-agent")
        self.assertTrue((tools.PROJECT_ROOT / "tools.py").is_file())

    def test_outside_path_is_rejected(self):
        self.assertFalse(tools._is_safe_path("/private/tmp/outside.txt"))

    def test_prefix_collision_is_rejected(self):
        sibling = tools.PROJECT_ROOT.parent / f"{tools.PROJECT_ROOT.name}-copy" / "secret.txt"
        self.assertFalse(tools._is_safe_path(sibling))

    def test_read_file_requires_small_valid_range(self):
        result = tools.read_file("tools.py", 1, 5)
        self.assertIn("import", result)
        self.assertIn("en fazla", tools.read_file("tools.py", 1, tools.MAX_READ_LINES + 1))
        self.assertIn("pozitif tam sayı", tools.read_file("tools.py", None, None))

    def test_search_uses_relative_paths_and_finds_known_code(self):
        result = tools.search_code("def read_file")
        self.assertIn("tools.py", result)
        self.assertNotIn(str(tools.PROJECT_ROOT), result)

    def test_search_prioritizes_source_code_over_test_files(self):
        result = tools.search_code("MAX_READ_LINES")
        first_result_line = result.splitlines()[1]
        self.assertIn("tools.py", first_result_line)
        self.assertIn("MAX_READ_LINES = 80", first_result_line)

    def test_symbol_search_handles_regex_characters_safely(self):
        result = tools.find_symbol("(")
        self.assertIn("Sembol", result)


if __name__ == "__main__":
    unittest.main()
