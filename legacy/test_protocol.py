import json
import unittest

import httpx
from pydantic import ValidationError

from protocol import (
    Assessment, Draft, ModelGateway, Plan, ProtocolError, Recovery, Review, RouteDecision,
    SearchRequest, Selection, TraceDraft,
    extract_json_object, render_stage_message, stage_schema, tool_call_signature, validate_review_coverage,
)


class ProtocolTests(unittest.TestCase):
    def test_verify_bad_answer_id_repairs_review_not_research(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            payload = {'supported': True, 'complete': True, 'issues': [], 'question_checklist': [
                {'requested_fact': 'Sonuç?', 'covered': True, 'explanation': 'Sonuç cevapta.',
                 'answer_ids': [99 if len(calls) == 1 else 1]}]}
            return {'message': {'content': json.dumps(payload)}}
        gateway = ModelGateway('fake', chat=chat)
        result = gateway.ask('VERIFY', Review, 'Check.', {
            'require_answer_coverage': True, 'findings': [{'answer': 'Hata döner.', 'evidence': [
                {'block_id': 'E1', 'file': 'example.py', 'start_line': 1, 'end_line': 1,
                 'quote': 'return "HATA"'}]}]})
        self.assertTrue(result.complete)
        self.assertEqual([item['stage'] for item in gateway.trace], ['VERIFY', 'VERIFY'])
        self.assertNotIn('answer_excerpt', calls[0]['format']['$defs']['QuestionCheck']['properties'])

    def test_verify_cannot_drop_previously_requested_fact(self):
        payload = {'supported': True, 'complete': True, 'issues': [], 'question_checklist': [
            {'requested_fact': 'Değer?', 'covered': True, 'explanation': 'Var.', 'answer_ids': [1]}]}
        gateway = ModelGateway('fake', chat=lambda **kwargs: {'message': {'content': json.dumps(payload)}})
        with self.assertRaises(ProtocolError):
            gateway.ask('VERIFY', Review, 'Check.', {
                'require_answer_coverage': True, 'findings': [{'answer': '23', 'evidence': [
                    {'block_id': 'E1', 'file': 'example.py', 'start_line': 1, 'end_line': 1,
                     'quote': 'LIMIT = 23'}]}]},
                allowed_review_facts=['Değer?', 'Sınır aşılırsa?'])

    def test_verify_missing_fact_with_empty_ids_is_content_failure(self):
        review = Review(supported=False, complete=False, issues=[], question_checklist=[
            {'requested_fact': 'Sonuç?', 'covered': False, 'answer_ids': [], 'explanation': 'Yazılmamış.'}])
        result = validate_review_coverage(review, [{'answer': 'Sınır 23.'}], use_ids=True)
        self.assertFalse(result.complete)
        self.assertIn('Cevapta eksik istek: Sonuç?', result.issues)

    def test_review_cannot_approve_a_missing_answer_excerpt(self):
        for excerpt in ('', 'Sınır aşılınca hata döner.'):
            with self.subTest(excerpt=excerpt):
                review = Review(supported=True, complete=True, issues=[], question_checklist=[
                    {'requested_fact': 'Sınır aşılınca ne olur?', 'covered': True,
                     'answer_excerpt': excerpt, 'explanation': 'Cevapta var.'}])
                checked = validate_review_coverage(review, [{'answer': 'Sınır 23 satırdır.'}])
                self.assertFalse(checked.complete)
                self.assertFalse(checked.question_checklist[0].covered)

    def test_review_accepts_a_real_answer_excerpt(self):
        review = Review(supported=True, complete=True, issues=[], question_checklist=[
            {'requested_fact': 'Ne döner?', 'covered': True,
             'answer_excerpt': 'Hata döner.', 'explanation': 'Sonuç açıklanmış.'}])
        checked = validate_review_coverage(review, [{'answer': 'Hata döner.'}])
        self.assertTrue(checked.complete)

    def test_review_cannot_approve_empty_checklist(self):
        checked = validate_review_coverage(Review(supported=True, complete=True, issues=[]), [])
        self.assertFalse(checked.complete)

    def test_review_false_coverage_overrides_complete_flag(self):
        review = Review(supported=True, complete=True, issues=[], question_checklist=[
            {'requested_fact': 'Sonuç?', 'covered': False, 'explanation': 'Eksik.'}])
        self.assertFalse(review.complete)

    def test_draft_rejects_missing_or_duplicate_answer_part(self):
        requirements = [{'id': 'Q1'}, {'id': 'Q2'}]
        for identifiers in (['Q1'], ['Q1', 'Q1']):
            with self.subTest(identifiers=identifiers):
                payload = {'claims': [{'requirement_id': key, 'answer': 'Sonuç.',
                                       'evidence_ids': ['E1']} for key in identifiers]}
                gateway = ModelGateway('fake', chat=lambda **kwargs: {
                    'message': {'content': json.dumps(payload)}})
                with self.assertRaises(ProtocolError):
                    gateway.ask('DRAFT', Draft, 'Answer.',
                                {'answer_requirements': requirements}, ['E1'])

    def test_draft_accepts_each_requested_part_once(self):
        payload = {'claims': [
            {'requirement_id': 'Q1', 'answer': 'Değer 23.', 'evidence_ids': ['E1']},
            {'requirement_id': 'Q2', 'answer': 'Sınır aşılırsa hata döner.', 'evidence_ids': ['E2']},
        ]}
        gateway = ModelGateway('fake', chat=lambda **kwargs: {
            'message': {'content': json.dumps(payload)}})
        result = gateway.ask('DRAFT', Draft, 'Answer.',
                             {'answer_requirements': [{'id': 'Q1'}, {'id': 'Q2'}]}, ['E1', 'E2'])
        self.assertEqual(len(result.claims), 2)

    def test_assessment_cannot_answer_with_a_missing_requested_fact(self):
        with self.assertRaises(ValidationError):
            Assessment(checks=[{'requested_fact': 'Değer', 'observed_answer': '',
                               'evidence_ids': [], 'status': 'missing'}],
                       missing_information='', action='answer', searches=[])

    def test_supported_assessment_requires_concrete_answer_and_evidence(self):
        for answer, ids in [('', ['E1']), ('Bir değer', [])]:
            with self.subTest(answer=answer, ids=ids), self.assertRaises(ValidationError):
                Assessment(checks=[{'requested_fact': 'Değer', 'observed_answer': answer,
                                   'evidence_ids': ids, 'status': 'supported'}],
                           missing_information='', action='answer', searches=[])

    def test_search_actions_cannot_have_empty_requests(self):
        with self.assertRaises(ValidationError):
            Assessment(established_facts=[], missing_information='Tanım eksik.', action='search', searches=[])
        with self.assertRaises(ValidationError):
            Recovery(decision_summary='Tanım eksik.', action='search', searches=[])

    def test_assessment_cannot_answer_while_reporting_missing_information(self):
        with self.assertRaises(ValidationError):
            Assessment.model_validate({
                "established_facts": [], "missing_information": "Çağrı yeri eksik.",
                "action": "answer", "searches": [],
            })

    def test_assessment_cannot_search_when_nothing_is_missing(self):
        with self.assertRaises(ValidationError):
            Assessment.model_validate({
                "established_facts": ["Tanım okundu."], "missing_information": "",
                "action": "search", "searches": [
                    {"tool": "find_references", "query": "MODEL_NAME"},
                ],
            })

    def test_object_parser_rejects_array_and_non_json(self):
        self.assertIsNone(extract_json_object("[1, 2]"))
        self.assertIsNone(extract_json_object(None))
        self.assertIsNone(extract_json_object("plain text"))

    def test_parser_accepts_single_fenced_object(self):
        self.assertEqual(extract_json_object('```json\n{"a":1}\n```'), {"a": 1})

    def test_signature_is_key_order_independent(self):
        self.assertEqual(tool_call_signature("read", {"b": 2, "a": 1}),
                         tool_call_signature("read", {"a": 1, "b": 2}))

    def test_query_cannot_be_used_as_an_arbitrary_tool(self):
        with self.assertRaises(ValidationError):
            SearchRequest(tool="some_source_function", query="x")

    def test_router_has_bounded_intent_tools_and_source_policy(self):
        route = RouteDecision.model_validate({
            "intent": "trace_call", "entities": ["client"], "source_policy": "code_only",
            "requirements": ["Çağrı yerini bul."], "decision_summary": "Runtime çağrısını izle.",
            "searches": [{"tool": "find_calls", "query": "client"}],
        })
        self.assertEqual(route.searches[0].tool, "find_calls")

    def test_router_intent_can_be_constrained_by_question_type(self):
        schema = stage_schema(RouteDecision, allowed_intents=["explain_behavior"])
        self.assertEqual(schema["properties"]["intent"]["enum"], ["explain_behavior"])

    def test_draft_cannot_supply_file_or_line_numbers(self):
        with self.assertRaises(ValidationError):
            Draft.model_validate({"claims": [{"answer": "x", "evidence_ids": ["L1"],
                                              "file": "invented.py", "start_line": 99}]})

    def test_normal_review_schema_is_compact_without_another_explanation(self):
        schema = stage_schema(Review)
        self.assertEqual(set(schema['properties']), {'issues', 'supported', 'complete'})
        result = Review.model_validate({'issues': [], 'supported': True, 'complete': True})
        self.assertEqual(result.question_checklist, [])

    def test_verify_generation_has_a_small_budget(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            return {'message': {'content': json.dumps({'issues': [], 'supported': True, 'complete': True})}}
        ModelGateway('fake', chat=chat).ask('VERIFY', Review, 'Check.', {})
        self.assertEqual(calls[0]['options']['num_predict'], 512)

    def test_qualified_definition_name_is_allowed_but_prose_is_not(self):
        self.assertEqual(SearchRequest(tool='find_symbol', query='Service.process').query, 'Service.process')
        with self.assertRaises(ValidationError):
            SearchRequest(tool='find_symbol', query='sınırı belirleyen sabit')

    def test_filename_query_for_symbol_tools_normalizes_to_find_file(self):
        req = SearchRequest.model_validate({'tool': 'find_symbol', 'query': 'agent.py'})
        self.assertEqual(req.tool, 'find_file')
        self.assertEqual(req.query, 'agent.py')

    def test_review_cannot_approve_while_reporting_an_issue(self):
        with self.assertRaises(ValidationError):
            Review.model_validate({
                "question_checklist": [{
                    "requested_fact": "Davranış", "covered": True,
                    "explanation": "Cevapta var.",
                }],
                "source_interpretation": "Kaynak cevabı destekliyor.",
                "issues": ["İlgisiz ek araştırma istendi."],
                "supported": True, "complete": True,
            })

    def test_source_id_enum_is_passed_to_generation_schema(self):
        schema = stage_schema(Selection, ["C2", "C4"])
        self.assertEqual(schema["properties"]["candidate_ids"]["items"]["enum"], ["C2", "C4"])
        schema = stage_schema(Draft, ["L3"])
        self.assertEqual(schema["$defs"]["DraftClaim"]["properties"]["evidence_ids"]["items"]["enum"], ["L3"])
        schema = stage_schema(TraceDraft, ["T2", "T4"])
        self.assertEqual(schema["properties"]["terminal_call_id"]["enum"], ["T2", "T4"])

    def test_reviewer_can_only_check_controller_owned_question_facts(self):
        question = "Fonksiyon ne döndürür ve mekanizma nedir?"
        schema = stage_schema(Review, allowed_review_facts=[question])
        checklist = schema["properties"]["question_checklist"]
        self.assertEqual(checklist["minItems"], 1)
        self.assertEqual(checklist["maxItems"], 1)
        self.assertEqual(
            schema["$defs"]["QuestionCheck"]["properties"]["requested_fact"]["enum"],
            [question],
        )

    def test_structured_call_uses_format_not_advisory_tool_list(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            return {"message": {"content": '{"candidate_ids":["C1"]}'}}
        result = ModelGateway("fake", chat=chat).ask("SELECT", Selection, "choose", {}, ["C1"])
        self.assertEqual(result.candidate_ids, ["C1"])
        self.assertIn("format", calls[0])
        self.assertNotIn("tools", calls[0])

    def test_thinking_is_disabled_by_default_and_forwarded_to_ollama(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            return {"message": {"content": '{"candidate_ids":["C1"]}'}}
        ModelGateway("fake", chat=chat).ask(
            "SELECT", Selection, "choose", {}, ["C1"],
        )
        self.assertIs(calls[0]["think"], False)

    def test_stage_specific_output_budget_is_forwarded(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            return {"message": {"content": '{"candidate_ids":["C1"]}'}}
        ModelGateway("fake", chat=chat, num_predict=1024).ask(
            "SELECT", Selection, "choose", {}, ["C1"],
        )
        self.assertEqual(calls[0]["options"]["num_predict"], 320)

    def test_fast_model_is_used_only_for_navigation_stages(self):
        calls = []
        responses = {
            "fast": '{"candidate_ids":["C1"]}',
            "main": '{"claims":[{"evidence_ids":["E1"],"answer":"tanı"}]}',
        }
        def chat(**kwargs):
            calls.append(kwargs)
            return {"message": {"content": responses[kwargs["model"]]}}
        gateway = ModelGateway(
            "main", fast_model_name="fast", chat=chat, num_predict=1024,
        )
        gateway.ask("SELECT", Selection, "choose", {}, ["C1"])
        gateway.ask("DRAFT", Draft, "diagnose", {}, ["E1"])
        self.assertEqual([call["model"] for call in calls], ["fast", "main"])

    def test_length_cutoff_retries_once_with_a_larger_budget(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {"message": {"content": '{"candidate_ids":["C1"]'},
                        "done_reason": "length"}
            return {"message": {"content": '{"candidate_ids":["C1"]}'}}
        result = ModelGateway("fake", chat=chat, num_predict=1024).ask(
            "SELECT", Selection, "choose", {}, ["C1"],
        )
        self.assertEqual(result.candidate_ids, ["C1"])
        self.assertEqual(len(calls), 2)
        self.assertGreater(
            calls[1]["options"]["num_predict"],
            calls[0]["options"]["num_predict"],
        )

    def test_invalid_json_has_only_one_repair_attempt(self):
        gateway = ModelGateway("fake", chat=lambda **kwargs: {"message": {"content": "not JSON"}})
        with self.assertRaises(ProtocolError):
            gateway.ask("ROUTE", RouteDecision, "route", {})
        self.assertEqual(len(gateway.trace), 2)

    def test_unknown_id_is_rejected_even_if_transport_ignores_schema(self):
        gateway = ModelGateway("fake", chat=lambda **kwargs: {
            "message": {"content": '{"candidate_ids":["C99"]}'},
        })
        with self.assertRaises(ProtocolError):
            gateway.ask("SELECT", Selection, "choose", {}, ["C1"])

    def test_trace_draft_must_include_every_required_chain_block(self):
        gateway = ModelGateway("fake", chat=lambda **kwargs: {
            "message": {"content": '{"claims":[{"evidence_ids":["E1"],"answer":"x"}]}'},
        })
        with self.assertRaises(ProtocolError):
            gateway.ask(
                "DRAFT", Draft, "trace", {}, allowed_ids=["E1", "E2"],
                required_ids=["E1", "E2"],
            )

    def test_required_trace_blocks_are_encoded_in_draft_schema(self):
        schema = stage_schema(
            Draft, allowed_ids=["E1", "E2", "E3"], required_ids=["E1", "E2", "E3"],
        )
        evidence_schema = schema["$defs"]["DraftClaim"]["properties"]["evidence_ids"]
        self.assertEqual(
            evidence_schema["allOf"],
            [{"contains": {"const": "E1"}}, {"contains": {"const": "E2"}},
             {"contains": {"const": "E3"}}],
        )

    def test_timeout_stops_without_fake_success(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            raise httpx.ReadTimeout("timeout")
        with self.assertRaises(ProtocolError):
            ModelGateway("fake", chat=chat).ask("SELECT", Selection, "choose", {}, ["C1"])
        self.assertEqual(len(calls), 2)

    def test_one_transient_timeout_is_retried(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise httpx.ReadTimeout("timeout")
            return {"message": {"content": '{"candidate_ids":["C1"]}'}}
        result = ModelGateway("fake", chat=chat).ask(
            "SELECT", Selection, "choose", {}, ["C1"],
        )
        self.assertEqual(result.candidate_ids, ["C1"])
        self.assertEqual(len(calls), 2)

    def test_call_and_time_budgets_are_enforced_before_request(self):
        for kwargs in ({"max_calls": 0}, {"budget_seconds": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ProtocolError):
                ModelGateway("fake", chat=lambda **kw: self.fail("must not call"), **kwargs).ask(
                    "PLAN", Plan, "plan", {},
                )

    def test_truncated_generation_is_never_accepted(self):
        gateway = ModelGateway("fake", chat=lambda **kwargs: {
            "message": {"content": '{"candidate_ids":["C1"]}'}, "done_reason": "length",
        })
        with self.assertRaises(ProtocolError):
            gateway.ask("SELECT", Selection, "choose", {}, ["C1"])
        self.assertEqual(len(gateway.trace), 2)

    def test_followup_queries_are_grounded_in_observed_names(self):
        schema = stage_schema(Assessment, allowed_queries=["page_width", "load_config"])
        self.assertEqual(schema["$defs"]["SearchRequest"]["properties"]["query"]["enum"],
                         ["page_width", "load_config"])
        gateway = ModelGateway("fake", chat=lambda **kw: {"message": {"content": json.dumps({
            "established_facts": [], "action": "search", "missing_information": "value", "searches": [
                {"tool": "search_code", "query": "the maximum amount"},
            ],
        })}})
        with self.assertRaises(ProtocolError):
            gateway.ask("ASSESS", Assessment, "choose", {}, allowed_queries=["page_width"])

    def test_recovery_queries_are_also_grounded_in_observed_names(self):
        schema = stage_schema(Recovery, allowed_queries=["page_width"])
        self.assertEqual(schema["$defs"]["SearchRequest"]["properties"]["query"]["enum"],
                         ["page_width"])

    def test_router_queries_are_grounded_in_question_or_listing_targets(self):
        schema = stage_schema(RouteDecision, allowed_queries=["qwen", "agent.py"])
        self.assertEqual(schema["$defs"]["SearchRequest"]["properties"]["query"]["enum"],
                         ["qwen", "agent.py"])

    def test_router_schema_couples_tool_with_question_anchored_target(self):
        actions = [{"tool": "search_code", "query": "Qwen"}]
        schema = stage_schema(
            RouteDecision, allowed_queries=["Qwen"], allowed_actions=actions,
        )
        item_schema = schema["properties"]["searches"]["items"]["anyOf"][0]
        self.assertEqual(item_schema["properties"]["tool"]["const"], "search_code")
        self.assertEqual(item_schema["properties"]["query"]["const"], "Qwen")

    def test_followup_schema_couples_tool_with_target_type(self):
        actions = [{"tool": "find_references", "query": "MODEL_NAME"}]
        schema = stage_schema(Assessment, allowed_queries=["MODEL_NAME"], allowed_actions=actions)
        item_schema = schema["properties"]["searches"]["items"]["anyOf"][0]
        self.assertEqual(item_schema["properties"]["tool"]["const"], "find_references")
        self.assertEqual(item_schema["properties"]["query"]["const"], "MODEL_NAME")

    def test_trace_frontier_can_force_search_before_answer(self):
        schema = stage_schema(
            Assessment,
            allowed_queries=["Gateway"],
            allowed_actions=[{"tool": "find_symbol", "query": "Gateway"}],
            forced_action="search",
        )
        self.assertEqual(schema["properties"]["action"]["const"], "search")
        self.assertEqual(schema["properties"]["searches"]["minItems"], 1)

    def test_terminal_trace_can_disallow_an_empty_search_decision(self):
        schema = stage_schema(Assessment, allowed_decisions=["answer", "stop"])
        self.assertEqual(schema["properties"]["action"]["enum"], ["answer", "stop"])

    def test_empty_query_targets_only_allow_no_searches(self):
        schema = stage_schema(Assessment, allowed_queries=[])
        self.assertEqual(schema["properties"]["searches"]["maxItems"], 0)

    def test_source_is_rendered_as_actual_indented_lines_not_an_escaped_json_string(self):
        quote = "def sample(value):\n    return value + 9"
        prompt = render_stage_message("ASSESS", {"source": [
            {"id": "E1", "file": "sample.py", "start_line": 4, "end_line": 5, "quote": quote},
        ]}, {})
        self.assertIn(quote, prompt)
        self.assertNotIn("\\n    return", prompt)
        self.assertIn("BEGIN UNTRUSTED SOURCE", prompt)

    def test_shared_citation_is_not_repeated_for_each_claim_in_reviewer_context(self):
        block = {"block_id": "E1", "file": "sample.py", "start_line": 1,
                 "end_line": 1, "quote": "amount = 29"}
        prompt = render_stage_message("VERIFY", {"findings": [
            {"answer": "first", "evidence": [block]}, {"answer": "second", "evidence": [block]},
        ]}, {})
        self.assertEqual(prompt.count("amount = 29"), 1)
