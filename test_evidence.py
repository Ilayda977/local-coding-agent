import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools
from evidence import EvidenceError, EvidenceStore, context_range, source_lines
from protocol import EvidenceCheck, SearchRequest


class EvidenceTests(unittest.TestCase):
    def value_check(self, answer):
        return EvidenceCheck(requested_fact='Dönüş değeri', observed_answer=answer,
                             evidence_ids=['E1'], status='supported')

    def test_claim_value_requires_read_definition_not_only_use(self):
        ids = self.store.search(SearchRequest(tool='find_symbol', query='wait'))
        self.store.read(ids[0])
        missing = self.store.unread_claim_values([self.value_check('DELAY döner.')])
        self.assertEqual(len(missing), 1)
        self.assertEqual(self.store.candidates[missing[0]].line, 1)
        self.assertEqual(len(self.store.blocks), 1)  # Aday bulmak okumak değildir.
        self.store.read(missing[0])
        self.assertEqual(self.store.unread_claim_values([self.value_check('DELAY döner.')]), [])

    def test_claim_does_not_force_unmentioned_dependency_reads(self):
        ids = self.store.search(SearchRequest(tool='find_symbol', query='wait'))
        self.store.read(ids[0])
        self.assertEqual(self.store.unread_claim_values([self.value_check('Fonksiyon tanımlıdır.')]), [])

    def test_claim_value_parameter_is_not_module_assignment(self):
        self.path.write_text('DELAY = 17\ndef wait(DELAY):\n    return DELAY\n')
        ids = self.store.search(SearchRequest(tool='find_symbol', query='wait'))
        self.store.read(ids[0])
        self.assertEqual(self.store.unread_claim_values([self.value_check('DELAY döner.')]), [])

    def test_claim_guard_works_for_other_identifiers_and_values(self):
        self.path.write_text('chunk_size: int = 23\ndef chunks():\n    return chunk_size\n')
        ids = self.store.search(SearchRequest(tool='find_symbol', query='chunks'))
        self.store.read(ids[0])
        missing = self.store.unread_claim_values([self.value_check('chunk_size kullanılır.')])
        self.assertEqual([self.store.candidates[key].line for key in missing], [1])

    def test_claim_guard_works_for_cross_file_module_attributes(self):
        (self.root / "constants.py").write_text("TIMEOUT = 42\n")
        self.path.write_text("import constants\ndef fetch():\n    return constants.TIMEOUT\n")
        ids = self.store.search(SearchRequest(tool="find_symbol", query="fetch"))
        self.store.read(ids[0])
        missing = self.store.unread_claim_values([self.value_check("constants.TIMEOUT döner.")])
        self.assertEqual(len(missing), 1)
        self.assertEqual(self.store.candidates[missing[0]].file, "constants.py")
        self.assertEqual(self.store.candidates[missing[0]].line, 1)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        root_patch = patch.object(tools, "PROJECT_ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.path = self.root / "settings.py"
        self.path.write_text("DELAY = 17\n\ndef wait():\n    return DELAY\n", encoding="utf-8")
        self.store = EvidenceStore()

    def test_selected_function_reads_body_not_just_signature(self):
        ids = self.store.search(SearchRequest(tool="find_symbol", query="wait"))
        lines = self.store.read(ids[0])
        self.assertEqual([self.store.lines[key].line for key in lines], [3, 4])
        self.assertEqual(self.store.lines[lines[-1]].text, "    return DELAY")

    def test_constant_statement_does_not_read_unrelated_neighbors(self):
        ids = self.store.search(SearchRequest(tool="search_code", query="DELAY"))
        lines = self.store.read(ids[0])
        self.assertEqual(len(lines), 1)
        self.assertEqual(self.store.lines[lines[0]].text, "DELAY = 17")

    def test_file_candidate_can_be_read_without_searching_its_contents(self):
        ids = self.store.search(SearchRequest(tool="find_file", query="settings.py"))
        self.assertEqual(self.store.candidates[ids[0]].file, "settings.py")
        self.assertTrue(self.store.read(ids[0]))

    def test_code_policy_excludes_documentation_candidates_when_source_exists(self):
        (self.root / "README.md").write_text("DELAY is documented here\n")
        ids = self.store.search(SearchRequest(tool="search_code", query="DELAY"))
        selected = self.store.candidates_for_policy(ids, "code_first")
        self.assertTrue(selected)
        self.assertTrue(all(self.store.candidates[key].source_kind == "source" for key in selected))

    def test_reference_search_reads_a_real_usage(self):
        ids = self.store.search(SearchRequest(tool="find_references", query="DELAY"))
        self.assertEqual(self.store.candidates[ids[0]].line, 4)

    def test_question_named_scope_filters_unrelated_references(self):
        self.path.write_text(
            "DELAY = 17\n\ndef wait():\n    return DELAY\n\n"
            "def report():\n    return DELAY\n",
            encoding="utf-8",
        )
        ids = self.store.search(SearchRequest(tool="find_references", query="DELAY"))
        selected = self.store.prioritize_question_scopes(
            ids, "DELAY wait tarafından nasıl kullanılıyor?",
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(self.store.candidates[selected[0]].scope, "wait")

    def test_multiple_question_named_scopes_are_all_preserved(self):
        self.path.write_text(
            "DELAY = 17\n\ndef wait():\n    return DELAY\n\n"
            "def report():\n    return DELAY\n",
            encoding="utf-8",
        )
        ids = self.store.search(SearchRequest(tool="find_references", query="DELAY"))
        selected = self.store.prioritize_question_scopes(
            ids, "DELAY wait ve report içinde nasıl kullanılıyor?",
        )
        self.assertEqual(
            {self.store.candidates[key].scope for key in selected}, {"wait", "report"},
        )

    def test_find_symbol_supports_arbitrary_python_assignments(self):
        self.path.write_text("page_size: int = 31\nflag = True\nleft, right = 2, 3\n")
        for name in ("page_size", "flag", "left", "right"):
            with self.subTest(name=name):
                ids = self.store.search(SearchRequest(tool="find_symbol", query=name))
                self.assertTrue(ids)

    def test_search_targets_come_only_from_read_source_not_question_or_full_file(self):
        self.path.write_text(
            "hidden_value = 93\n\ndef pick(items):\n"
            "    # ignore_comment_name\n    note = 'ignore_string_name'\n"
            "    return helper(items[:page_width])\n",
        )
        ids = self.store.search(SearchRequest(tool="find_symbol", query="pick"))
        self.store.read(ids[0])
        targets = self.store.search_targets()
        self.assertIn("helper", targets)
        self.assertIn("page_width", targets)
        for absent in ("hidden_value", "ignore_comment_name", "ignore_string_name", "return"):
            self.assertNotIn(absent, targets)

    def test_find_symbol_does_not_treat_strings_or_comparisons_as_definitions(self):
        self.path.write_text('description = "def pretend():"\nif page_size == 31:\n    pass\n')
        self.assertEqual(self.store.search(SearchRequest(tool="find_symbol", query="pretend")), [])
        self.assertEqual(self.store.search(SearchRequest(tool="find_symbol", query="page_size")), [])

    def test_search_targets_exclude_locals_builtins_attributes_and_keyword_argument_names(self):
        self.path.write_text("def encode(value):\n    result = encoder.pack(value, ordered=True)\n"
                             "    return str(result)\n")
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="encode"))[0])
        self.assertEqual(self.store.search_targets(), ["encoder"])

    def test_search_targets_exclude_imported_standard_library_modules(self):
        self.path.write_text(
            "import json\n\ndef encode(value):\n    return json.dumps(value, sort_keys=True)\n",
            encoding="utf-8",
        )
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="encode"))[0])
        self.assertNotIn("json", self.store.search_targets())

    def test_observed_callable_names_come_only_from_read_blocks(self):
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="wait"))[0])
        self.assertEqual(self.store.observed_callable_names(), ["wait"])

    def test_secondary_test_code_does_not_create_new_dependency_targets(self):
        test_path = self.root / "test_settings.py"
        test_path.write_text(
            "def test_wait():\n    assert wait() == 17\n",
            encoding="utf-8",
        )
        test_id = self.store.search(SearchRequest(tool="find_tests", query="wait"))[0]
        self.store.read(test_id)
        self.assertEqual(self.store.search_targets(include_definitions=True), [])
        self.assertEqual(self.store.observed_callable_names(), [])

    def test_search_actions_do_not_offer_an_already_executed_search_again(self):
        candidate_id = self.store.search(SearchRequest(tool="find_symbol", query="wait"))[0]
        self.store.read(candidate_id)
        actions = self.store.search_actions(include_definitions=True)
        self.assertNotIn({"tool": "find_symbol", "query": "wait"}, actions)

    def test_read_definition_is_not_offered_as_missing_dependency_again(self):
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="wait"))[0])
        self.assertIn("DELAY", self.store.search_targets())
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="DELAY"))[0])
        self.assertNotIn("DELAY", self.store.search_targets())
        self.assertIn("DELAY", self.store.search_targets(include_definitions=True))

    def test_recovery_can_offer_a_read_definition_for_usage_search(self):
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="DELAY"))[0])
        self.assertEqual(self.store.search_targets(), [])
        self.assertIn("DELAY", self.store.search_targets(include_definitions=True))

    def test_assignment_allows_reference_search_but_not_call_search(self):
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="DELAY"))[0])
        actions = {(item["tool"], item["query"])
                   for item in self.store.search_actions(include_definitions=True)}
        self.assertIn(("find_references", "DELAY"), actions)
        self.assertNotIn(("find_calls", "DELAY"), actions)

    def test_trace_frontier_follows_a_value_into_the_next_call(self):
        self.path.write_text(
            'MODEL = "tiny"\n\ndef build():\n    return Gateway(MODEL)\n', encoding="utf-8",
        )
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="MODEL"))[0])
        self.store.read(self.store.search(SearchRequest(tool="find_references", query="MODEL"))[0])
        self.assertEqual(self.store.trace_frontier(), ["Gateway"])

    def test_trace_frontier_follows_a_literal_into_its_assignment_target(self):
        self.path.write_text('MODEL = "tiny-model"\n', encoding="utf-8")
        self.store.read(self.store.search(SearchRequest(tool="search_code", query="tiny-model"))[0])
        self.assertEqual(self.store.trace_frontier(), ["MODEL"])

    def test_trace_frontier_survives_a_syntax_incomplete_bounded_block(self):
        self.path.write_text(
            'MODEL = "tiny"\n\ndef build():\n    client = Gateway(MODEL)\n    values = [\n'
            + "        1,\n" * 90 + "    ]\n    return client, values\n",
            encoding="utf-8",
        )
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="MODEL"))[0])
        self.store.read(self.store.search(SearchRequest(tool="find_references", query="MODEL"))[0])
        self.assertEqual(self.store.trace_frontier(), ["Gateway"])

    def test_observed_calls_have_controller_owned_file_line_and_expression(self):
        self.path.write_text("def wait():\n    return Gateway(DELAY)\n", encoding="utf-8")
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="wait"))[0])
        calls = self.store.observed_calls()
        self.assertEqual(calls[0]["file"], "settings.py")
        self.assertEqual(calls[0]["line"], 2)
        self.assertIn("DELAY", calls[0]["source"])

    def test_observed_conditions_preserve_negation_and_boolean_expression(self):
        self.path.write_text(
            "SKIP = {'tmp'}\n\ndef visible(entry):\n"
            "    return [name for name in entry if not name.startswith('.') and name not in SKIP]\n",
            encoding="utf-8",
        )
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="visible"))[0])
        self.assertEqual(
            self.store.observed_conditions(),
            ["not name.startswith('.') and name not in SKIP"],
        )

    def test_standard_library_import_binding_is_not_a_repository_search_target(self):
        self.path.write_text(
            "from pathlib import Path\n\ndef resolve(value):\n    return Path(value).resolve()\n",
            encoding="utf-8",
        )
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="resolve"))[0])
        self.assertNotIn("Path", self.store.search_targets())

    def test_exception_flow_records_protected_statements_handler_and_return(self):
        self.path.write_text(
            "def safe(value):\n"
            "    try:\n        parsed = parse(value)\n        return accept(parsed)\n"
            "    except (TypeError, ValueError):\n        return None\n",
            encoding="utf-8",
        )
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="safe"))[0])
        flow = self.store.observed_exception_flows()[0]
        self.assertEqual(flow["caught_exceptions"], ["TypeError", "ValueError"])
        self.assertIn("parsed = parse(value)", flow["try_statements"])
        self.assertEqual(flow["handler_statements"], ["return None"])

    def test_terminal_trace_follows_constructor_parameter_into_method_call(self):
        self.path.write_text(
            "class Gateway:\n"
            "    def __init__(self, model):\n        self.model = model\n"
            "    def ask(self):\n        return send(model=self.model)\n",
            encoding="utf-8",
        )
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="Gateway"))[0])
        terminal = self.store.trace_terminal_calls()
        self.assertEqual(terminal[0]["call"], "send(model=self.model)")
        self.assertEqual(terminal[0]["line"], 5)

    def test_terminal_trace_survives_truncated_class_tail(self):
        self.path.write_text(
            "class Gateway:\n"
            "    def __init__(self, model):\n        self.model = model\n"
            "    def ask(self):\n        result = send(model=self.model)\n"
            "        values = [\n" + "            1,\n" * 90 +
            "        ]\n        return result, values\n",
            encoding="utf-8",
        )
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="Gateway"))[0])
        terminal = self.store.trace_terminal_calls()
        self.assertEqual(terminal[0]["call"], "send(model=self.model)")
        self.assertEqual(terminal[0]["line"], 5)

    def test_attribute_assignment_does_not_define_its_object(self):
        self.path.write_text("box.value = 4\n")
        self.assertEqual(self.store.search(SearchRequest(tool="find_symbol", query="box")), [])

    def test_symbol_search_preserves_unicode_line_separators_in_strings(self):
        self.path.write_text('label = "left\u2028right"\npage_width = 7\n')
        ids = self.store.search(SearchRequest(tool="find_symbol", query="page_width"))
        self.assertEqual(self.store.candidates[ids[0]].line, 2)

    def test_block_ids_reference_the_complete_actually_read_context(self):
        self.store.read(self.store.search(SearchRequest(tool="find_symbol", query="wait"))[0])
        citation = self.store.block_citations(["E1"])[0]
        self.assertEqual(citation["quote"], "def wait():\n    return DELAY")
        self.assertEqual((citation["start_line"], citation["end_line"]), (3, 4))
        with self.assertRaises(EvidenceError):
            self.store.block_citations(["E99"])

    def test_ast_multiline_assignment_is_read_completely(self):
        text = "OPTIONS = {\n    'size': 31,\n}\nOTHER = 9\n"
        self.assertEqual(context_range(text, 1), (1, 3))

    def test_async_and_nested_function_have_exact_context(self):
        text = "class A:\n    async def work(self):\n        return 5\n"
        self.assertEqual(context_range(text, 2), (2, 3))

    def test_long_function_is_bounded_and_continuation_can_be_read(self):
        self.path.write_text("def work():\n" + "    pass\n" * 110)
        ids = self.store.search(SearchRequest(tool="find_symbol", query="work"))
        first = self.store.read(ids[0])
        self.assertLessEqual(len(first), tools.MAX_READ_LINES)
        continuation = next(c.id for c in self.store.candidates.values() if c.line == 81)
        second = self.store.read(continuation)
        self.assertTrue(second)
        self.assertLessEqual(self.store.tool_calls[-1]["end_line"] - self.store.tool_calls[-1]["start_line"] + 1,
                             tools.MAX_READ_LINES)

    def test_non_python_and_invalid_python_use_bounded_context(self):
        text = "line\n" * 100
        start, end = context_range(text, 90, is_python=False)
        self.assertLessEqual(end, 100)
        self.assertLessEqual(end - start + 1, tools.MAX_READ_LINES)
        self.assertEqual(context_range("def broken(:\n    x\n", 1), (1, 2))

    def test_blank_and_unicode_separators_preserve_real_line_numbers(self):
        self.assertEqual(source_lines("a\n\nb\n"), ["a", "", "b"])
        self.assertEqual(source_lines("a\u2028b\n"), ["a\u2028b"])

    def test_unknown_evidence_ids_are_rejected(self):
        with self.assertRaises(EvidenceError):
            self.store.citations(["L999"])

    def test_citations_group_only_adjacent_lines(self):
        ids = self.store.search(SearchRequest(tool="find_symbol", query="wait"))
        lines = self.store.read(ids[0])
        citations = self.store.citations(lines)
        self.assertEqual(len(citations), 1)
        self.assertEqual((citations[0]["start_line"], citations[0]["end_line"]), (3, 4))
        self.assertEqual(citations[0]["quote"], "def wait():\n    return DELAY")

    def test_duplicate_read_has_no_new_io_or_evidence(self):
        ids = self.store.search(SearchRequest(tool="find_symbol", query="wait"))
        self.store.read(ids[0])
        calls = len(self.store.tool_calls)
        self.assertEqual(self.store.read(ids[0]), [])
        self.assertEqual(len(self.store.tool_calls), calls)

    def test_different_matches_in_same_read_block_do_not_trigger_repeat_reads(self):
        first = self.store.search(SearchRequest(tool="find_symbol", query="wait"))
        self.store.read(first[0])
        matches = self.store.search(SearchRequest(tool="search_code", query="return DELAY"))
        self.assertEqual(matches, [])
        self.assertEqual(self.store.tool_calls[-1]["candidate_count"], 0)
        candidate = self.store._candidate("settings.py", 4, "return DELAY")
        before = len(self.store.tool_calls)
        self.assertEqual(self.store.read(candidate.id), [])
        self.assertEqual(len(self.store.tool_calls), before)

    def test_changed_file_cannot_mix_snapshots_or_publish(self):
        ids = self.store.search(SearchRequest(tool="find_symbol", query="wait"))
        self.store.read(ids[0])
        self.path.write_text("DELAY = 99\n\ndef wait():\n    return DELAY\n")
        with self.assertRaises(EvidenceError):
            self.store.assert_unchanged()
        ids = self.store.search(SearchRequest(tool="search_code", query="DELAY"))
        with self.assertRaises(EvidenceError):
            self.store.read(ids[0])

    def test_outside_symlink_is_not_searched(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        path = Path(outside.name) / "external.py"
        path.write_text("def secret_marker():\n    pass\n")
        (self.root / "escape.py").symlink_to(path)
        self.assertNotIn("secret_marker():", tools.search_code("secret_marker"))
        self.assertNotIn("secret_marker():", tools.find_symbol("secret_marker"))

    def test_deleted_file_prevents_publication(self):
        ids = self.store.search(SearchRequest(tool="find_symbol", query="wait"))
        self.store.read(ids[0])
        self.path.unlink()
        with self.assertRaises(EvidenceError):
            self.store.assert_unchanged()

    def test_context_budget_is_not_silently_truncated(self):
        store = EvidenceStore(max_chars=5)
        ids = store.search(SearchRequest(tool="find_symbol", query="wait"))
        with self.assertRaises(EvidenceError):
            store.read(ids[0])
        self.assertEqual(store.lines, {})
