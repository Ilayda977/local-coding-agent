import unittest

import agent


class ToolCallExtractionTests(unittest.TestCase):
    def test_keeps_native_ollama_tool_call(self):
        native_call = {"function": {"name": "search_code", "arguments": {"query": "root"}}}
        self.assertEqual(agent.extract_tool_calls({"tool_calls": [native_call]}), [native_call])

    def test_parses_json_tool_call_written_in_content(self):
        message = {"content": '{"name": "search_code", "arguments": {"query": "PROJECT_ROOT"}}'}
        calls = agent.extract_tool_calls(message)
        self.assertEqual(calls[0]["function"]["name"], "search_code")
        self.assertEqual(calls[0]["function"]["arguments"]["query"], "PROJECT_ROOT")

    def test_parses_json_tool_call_written_in_markdown_fence(self):
        message = {
            "content": "```json\n{\"name\": \"read_file\", \"arguments\": {\"file_path\": \"tools.py\"}}\n```"
        }
        calls = agent.extract_tool_calls(message)
        self.assertEqual(calls[0]["function"]["name"], "read_file")

    def test_keeps_normal_final_answer_as_text(self):
        self.assertEqual(agent.extract_tool_calls({"content": "Bulgumu paylaşıyorum."}), [])

    def test_tool_call_signature_is_stable_for_same_arguments(self):
        first = agent.tool_call_signature("search_code", {"query": "MAX_READ_LINES"})
        second = agent.tool_call_signature("search_code", {"query": "MAX_READ_LINES"})
        self.assertEqual(first, second)

    def test_system_prompt_requires_discovery_before_unknown_file_read(self):
        self.assertIn("daha önce list_files, search_code veya find_symbol sonucunda", agent.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
