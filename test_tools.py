import unittest
from pathlib import Path

import tools


class ReadOnlyToolTests(unittest.TestCase):
    def test_qualified_method_definition_is_found_structurally(self):
        result = tools.find_symbol('EvidenceStore.assert_unchanged')
        self.assertIn('evidence.py (Satır ', result)
        self.assertIn('def assert_unchanged(self):', result)
        self.assertNotIn('def read(', result)
        self.assertIn('Sembol bulunamadı', tools.find_symbol('NonexistentOwner.assert_unchanged'))

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

    def test_search_has_case_insensitive_fallback_for_natural_casing(self):
        result = tools.search_code("QWEN2.5-CODER:7B")
        self.assertIn("agent.py", result)
        self.assertIn("qwen2.5-coder:7b", result)

    def test_search_prioritizes_source_code_over_test_files(self):
        result = tools.search_code("MAX_READ_LINES")
        first_result_line = result.splitlines()[1]
        self.assertIn("tools.py", first_result_line)
        self.assertIn("MAX_READ_LINES = 80", first_result_line)

    def test_search_prioritizes_runtime_text_over_comment_mentions(self):
        implementation = tools._result_priority(
            Path("runtime.py"), 'MODEL = "local-engine"', "local-engine",
        )
        comment = tools._result_priority(
            Path("runtime.py"), "# local-engine is only an example", "local-engine",
        )
        self.assertLess(implementation, comment)

    def test_symbol_search_handles_regex_characters_safely(self):
        result = tools.find_symbol("(")
        self.assertIn("Sembol", result)

    def test_find_file_searches_the_path_not_file_contents(self):
        result = tools.find_file("agent.py")
        self.assertIn("agent.py (Satır 1)", result)
        self.assertNotIn("README.md", result)

    def test_find_references_excludes_definition_and_docs(self):
        result = tools.find_references("MODEL_NAME")
        self.assertIn("agent.py", result)
        self.assertIn("MODEL_NAME, think=MODEL_THINK, fast_model_name=FAST_MODEL_NAME", result)
        self.assertNotIn("qwen2.5-coder:7b", result)
        self.assertNotIn("README.md", result)

    def test_find_calls_returns_real_python_call_sites(self):
        result = tools.find_calls("chat")
        self.assertIn("protocol.py", result)
        self.assertIn("response = chat(", result)
        self.assertNotIn("README.md", result)

    def test_find_tests_returns_the_test_function_that_uses_a_symbol(self):
        result = tools.find_tests("tool_call_signature")
        self.assertIn("test_protocol.py", result)
        self.assertIn("test_signature_is_key_order_independent", result)


if __name__ == "__main__":
    unittest.main()
