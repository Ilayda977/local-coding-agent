"""Controller testlerinde model taklit edilir; gerçek model değerlendirmesi ayrıdır."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import agent
import tools
from protocol import ModelGateway, RouteDecision, Selection


class ScriptedGateway:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.trace = []
        self.inputs = []

    def ask(self, stage, model, instruction, data, allowed_ids=None, allowed_queries=None,
            allowed_actions=None, forced_action=None, allowed_decisions=None, required_ids=None):
        self.trace.append({"stage": stage})
        self.inputs.append(data)
        response = next(self.responses)
        if callable(response):
            response = response(data, allowed_ids)
        return model.model_validate(response)


def plan(query="normalize"):
    return {"intent": "explain_behavior", "entities": [query],
            "source_policy": "code_first", "decision_summary": "Kod davranışını araştır.",
            "requirements": ["Davranışı açıkla."],
            "searches": [{"tool": "find_symbol", "query": query}]}


def ready():
    return {"established_facts": ["İstenen davranış okunan kaynakta görüldü."],
            "action": "answer", "missing_information": "", "searches": []}


def draft(answer="Boşlukları temizler.", ids=None):
    return {"claims": [{"answer": answer, "evidence_ids": ids or ["E1"]}]}


def review(ok=True):
    return {"question_checklist": [{
                "requested_fact": "İstenen davranış", "covered": ok,
                "explanation": "Cevapta var." if ok else "Cevapta yok.",
            }],
            "source_interpretation": "Kaynak davranışı incelendi.",
            "supported": ok, "complete": ok, "issues": [] if ok else ["İddia kanıtta yok."]}


def recover(action="revise", query=None):
    searches = [] if query is None else [{"tool": "find_symbol", "query": query}]
    return {"decision_summary": "Eksik kanıta göre bir sonraki adım seçildi.",
            "action": action, "searches": searches}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        root_patch = patch.object(tools, "PROJECT_ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        (self.root / "normalizer.py").write_text(
            "def normalize(text):\n    return text.strip()\n", encoding="utf-8",
        )

    def run_workflow(self, responses, question="Fonksiyon ne yapıyor?"):
        gateway = ScriptedGateway(responses)
        with redirect_stdout(io.StringIO()):
            result = agent.run_agent(question, gateway=gateway)
        return result, gateway

    def simple_responses(self):
        return [plan(), {"candidate_ids": ["C1"]}, ready(), draft(), review()]

    def test_underspecified_placeholder_stops_before_tools_and_model(self):
        gateway = ScriptedGateway([])
        output = io.StringIO()
        with redirect_stdout(output):
            result = agent.run_agent("soru", gateway=gateway)
        self.assertEqual(result.status, "invalid_request")
        self.assertEqual(result.stages, [])
        self.assertEqual(result.tool_calls, [])
        self.assertEqual(result.model_trace, [])
        self.assertIn("aranacak dosya", output.getvalue())

    def test_short_concrete_request_is_not_rejected(self):
        for question in ("MODEL_NAME", "agent.py", "qwen2.5-coder:7b"):
            with self.subTest(question=question):
                self.assertEqual(agent._request_validation_error(question), "")

    def test_stages_cannot_skip_listing_reading_or_verification(self):
        result, _ = self.run_workflow(self.simple_responses())
        self.assertEqual(result.status, "review_required")
        self.assertEqual(result.stages, [
            "LIST", "ROUTE", "SEARCH", "SELECT", "READ", "ASSESS",
            "DRAFT", "GROUNDING", "VERIFY", "RESULT",
        ])
        self.assertEqual(result.tool_calls[0]["tool"], "list_files")

    def test_file_line_and_quote_come_from_store_not_model(self):
        result, _ = self.run_workflow(self.simple_responses())
        evidence = result.findings[0]["evidence"][0]
        self.assertEqual((evidence["file"], evidence["start_line"], evidence["end_line"]),
                         ("normalizer.py", 1, 2))
        self.assertEqual(evidence["quote"], "def normalize(text):\n    return text.strip()")

    def test_model_selects_second_definition_without_controller_overriding(self):
        (self.root / "another.py").write_text("def normalize(x):\n    return x.upper()\n")
        responses = self.simple_responses()
        responses[1] = lambda data, ids: {
            "candidate_ids": [next(c["id"] for c in data["candidates"] if c["file"] == "normalizer.py")],
        }
        result, _ = self.run_workflow(responses)
        self.assertEqual(result.findings[0]["evidence"][0]["file"], "normalizer.py")

    def test_router_can_open_a_named_file_and_select_a_definition_inside_it(self):
        (self.root / "settings.py").write_text(
            '"""settings"""\nMODEL_ALIAS = "local-model"\n', encoding="utf-8",
        )
        route = {
            "intent": "find_definition", "entities": ["settings.py", "MODEL_ALIAS"],
            "source_policy": "code_only", "decision_summary": "Named file and symbol.",
            "requirements": ["MODEL_ALIAS tanımını bul."],
            "searches": [
                {"tool": "find_file", "query": "settings.py"},
                {"tool": "find_symbol", "query": "MODEL_ALIAS"},
            ],
        }
        responses = [
            route,
            lambda data, ids: {"candidate_ids": [
                next(c["id"] for c in data["candidates"] if c["line"] == 2)
            ]},
            ready(), draft("MODEL_ALIAS local-model değeridir."), review(),
        ]
        result, gateway = self.run_workflow(
            responses, question="settings.py içindeki MODEL_ALIAS tanımını bul.",
        )
        self.assertEqual(result.status, "review_required")
        self.assertEqual(result.findings[0]["evidence"][0]["file"], "settings.py")
        self.assertEqual(result.findings[0]["evidence"][0]["start_line"], 2)
        self.assertEqual({c["source_kind"] for c in gateway.inputs[1]["candidates"]}, {"source"})

    def test_locate_file_assessment_does_not_expand_into_symbol_searches(self):
        route = {
            "intent": "locate_file", "entities": ["normalizer.py"],
            "source_policy": "code_only", "decision_summary": "Named file inspection.",
            "requirements": ["Dosyayı bul ve başlangıç amacını açıkla."],
            "searches": [{"tool": "find_file", "query": "normalizer.py"}],
        }
        result, gateway = self.run_workflow([
            route, {"candidate_ids": ["C1"]}, ready(),
            draft("Dosya metni normalize eder."), review(),
        ], question="normalizer.py dosyasını bul ve başındaki amacı açıkla.")
        self.assertEqual(result.status, "review_required")
        assessment_input = gateway.inputs[2]
        self.assertEqual(assessment_input["search_targets"], [])
        self.assertEqual(assessment_input["available_search_actions"], [])

    def test_runtime_route_does_not_offer_readme_when_source_match_exists(self):
        (self.root / "README.md").write_text("local-model is documented twice: local-model\n")
        (self.root / "normalizer.py").write_text('MODEL = "local-model"\n')
        runtime_route = {
            "intent": "general_code_search", "entities": ["local-model"],
            "source_policy": "code_first", "decision_summary": "Trace runtime model usage.",
            "requirements": ["Modelin runtime yerini bul."],
            "searches": [{"tool": "search_code", "query": "local-model"}],
        }
        result, gateway = self.run_workflow([
            runtime_route, {"candidate_ids": ["C1"]}, ready(),
            draft("Model kaynak kodunda yapılandırılır."), review(),
        ], question="local-model nerede çağrılıyor?")
        self.assertEqual(result.status, "review_required")
        self.assertEqual([c["file"] for c in gateway.inputs[1]["candidates"]], ["normalizer.py"])

    def test_initial_router_targets_come_from_question_not_guessed_listing_files(self):
        targets = agent._initial_search_targets(
            "agent.py içindeki MODEL_NAME nerede?", ". içindeki dosyalar:\nagent.py\nREADME.md",
        )
        for expected in ("agent.py", "MODEL_NAME"):
            self.assertIn(expected, targets)
        self.assertNotIn("README.md", targets)
        self.assertNotIn("modelin çağrıldığı yeri ara", targets)

    def test_initial_router_cannot_guess_a_file_for_a_literal_model_name(self):
        listing = ". içindeki dosyalar:\nagent.py\ntools.py\nREADME.md"
        actions = agent._initial_search_actions(
            "Qwen modeli nerede yapılandırılıyor?", listing,
        )
        self.assertIn({"tool": "search_code", "query": "Qwen"}, actions)
        self.assertFalse(any(item["tool"] == "find_file" for item in actions))

    def test_initial_router_can_find_a_file_explicitly_named_by_the_user(self):
        actions = agent._initial_search_actions(
            "agent.py dosyasını bul", ". içindeki dosyalar:\nagent.py\nREADME.md",
        )
        self.assertIn({"tool": "find_file", "query": "agent.py"}, actions)

    def test_trace_frontier_prefers_definition_tool_over_text_search(self):
        actions = [
            {"tool": "search_code", "query": "Gateway"},
            {"tool": "find_symbol", "query": "Gateway"},
        ]
        self.assertEqual(agent._preferred_trace_actions(actions, ["Gateway"]), [
            {"tool": "find_symbol", "query": "Gateway"},
        ])

    def test_trace_frontier_prefers_references_for_an_observed_value(self):
        actions = [
            {"tool": "search_code", "query": "MODEL_ALIAS"},
            {"tool": "find_references", "query": "MODEL_ALIAS"},
        ]
        self.assertEqual(agent._preferred_trace_actions(actions, ["MODEL_ALIAS"]), [
            {"tool": "find_references", "query": "MODEL_ALIAS"},
        ])

    def test_verified_terminal_call_skips_fallible_assessment_verdict(self):
        (self.root / "normalizer.py").write_text(
            "class Gateway:\n"
            "    def __init__(self, model):\n        self.model = model\n"
            "    def ask(self):\n        return send(model=self.model)\n",
            encoding="utf-8",
        )
        route = {
            "intent": "trace_call", "entities": ["Gateway"],
            "source_policy": "code_only", "decision_summary": "Çağrıyı izle.",
            "requirements": ["Terminal çağrıyı bul."],
            "searches": [{"tool": "find_symbol", "query": "Gateway"}],
        }
        result, gateway = self.run_workflow([
            route, {"candidate_ids": ["C1"]},
            {"terminal_call_id": "T1", "answer": "Model send çağrısına aktarılır."},
            review(),
        ], question="Gateway modeli nerede çağırıyor?")
        self.assertEqual(result.status, "review_required")
        self.assertIn("ASSESS", result.stages)
        self.assertNotIn("ASSESS", [item["stage"] for item in gateway.trace])
        self.assertIn("send(model=self.model)", result.findings[0]["evidence"][0]["quote"])

    def test_trace_location_claim_is_removed_without_an_unrelated_search(self):
        (self.root / "normalizer.py").write_text(
            "class Gateway:\n"
            "    def __init__(self, model):\n        self.model = model\n"
            "    def ask(self):\n        return send(model=self.model)\n",
            encoding="utf-8",
        )
        route = {
            "intent": "trace_call", "entities": ["Gateway"],
            "source_policy": "code_only", "decision_summary": "Çağrıyı izle.",
            "requirements": ["Terminal çağrıyı bul."],
            "searches": [{"tool": "find_symbol", "query": "Gateway"}],
        }
        result, _ = self.run_workflow([
            route, {"candidate_ids": ["C1"]},
            {"terminal_call_id": "T1", "answer": "Model satır 999 içinde send çağrısına aktarılır."},
            review(),
        ], question="Gateway modeli nerede çağırıyor?")
        self.assertEqual(result.status, "review_required")
        self.assertNotIn("999", result.findings[0]["answer"])
        self.assertNotIn("REVISE", result.stages)
        self.assertEqual(
            [call["tool"] for call in result.tool_calls], ["list_files", "find_symbol", "read_file"],
        )

    def test_line_location_normalizer_preserves_version_numbers(self):
        answer = (
            "Model qwen2.5-coder:7b; agent.py dosyasında satır 16'da, "
            "16. satırda ve (227-306 satırlar arası) kullanılır."
        )
        normalized = agent._strip_model_line_locations(answer)
        self.assertIn("qwen2.5-coder:7b", normalized)
        for location in ("satır 16", "16. satır", "227-306"):
            self.assertNotIn(location, normalized)

    def test_typo_in_generic_task_word_is_not_a_repository_search_target(self):
        question = "bu repoda nerede qwen mmodeli çağrılıyor"
        self.assertEqual(
            agent._normalize_question(question),
            "bu repoda nerede qwen modeli çağrılıyor",
        )
        targets = agent._initial_search_targets(
            question, ". içindeki dosyalar:\nagent.py\nprotocol.py",
        )
        self.assertIn("qwen", targets)
        for noise in ("mmodeli", "modeli", "çağrılıyor", "repoda", "nerede"):
            self.assertNotIn(noise, targets)

    def test_normalizer_does_not_change_valid_inflected_words(self):
        question = "MAX_SEARCH_RESULTS sabitinin tanımlandığı dosyayı bul"
        self.assertEqual(agent._normalize_question(question), question)

    def test_quoted_generic_word_remains_an_explicit_search_target(self):
        targets = agent._initial_search_targets(
            "`model` metnini ara", ". içindeki dosyalar:\nagent.py",
        )
        self.assertIn("model", targets)

    def test_all_model_stages_receive_the_normalized_question(self):
        result, gateway = self.run_workflow(
            self.simple_responses(), question="qwen mmodeli nerede?",
        )
        self.assertEqual(result.question, "qwen mmodeli nerede?")
        self.assertTrue(gateway.inputs)
        self.assertTrue(all(
            data["question"] == "qwen modeli nerede?"
            for data in gateway.inputs if "question" in data
        ))

    def test_immediate_answer_without_any_read_is_rejected(self):
        result, _ = self.run_workflow([plan("missing_symbol"), ready()])
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.findings, [])
        self.assertNotIn("DRAFT", result.stages)

    def test_model_cannot_invent_evidence_id_even_if_reviewer_would_approve(self):
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, ready(), draft(ids=["L999"]),
        ])
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.findings, [])
        self.assertNotIn("VERIFY", result.stages)

    def test_unsupported_answer_is_not_published(self):
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, ready(),
            draft("Uydurma davranış."), review(False), recover(),
            draft("Başka uydurma."), review(False), recover("stop"),
        ])
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.findings, [])
        self.assertEqual(result.stages.count("REVISE"), 1)

    def test_failed_behavior_draft_uses_repository_test_as_secondary_evidence(self):
        (self.root / "test_normalizer.py").write_text(
            "def test_normalize_is_stable():\n"
            "    assert normalize(' value ') == normalize('value')\n",
            encoding="utf-8",
        )
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, ready(),
            draft("Normalize sonucu kararlı değildir."), review(False),
            {"candidate_ids": ["C2"]}, ready(),
            draft("Normalize iki girdide de aynı sonucu verir.", ["E1", "E2"]), review(),
        ], question="normalize eşdeğer girdilerde aynı sonucu üretir mi?")
        self.assertEqual(result.status, "review_required")
        self.assertTrue(any(
            call.get("tool") == "find_tests" and call.get("query") == "normalize"
            for call in result.tool_calls
        ))
        self.assertEqual(result.stages.count("RECOVER"), 1)
        self.assertEqual(result.stages.count("REDRAFT"), 1)

    def test_inconclusive_assessment_uses_repository_test_before_stopping(self):
        (self.root / "test_normalizer.py").write_text(
            "def test_normalize_is_stable():\n"
            "    assert normalize(' value ') == normalize('value')\n",
            encoding="utf-8",
        )
        inconclusive = {
            "established_facts": [], "action": "search",
            "missing_information": "Davranışı doğrulayacak ek kanıt gerekli.", "searches": [],
        }
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, inconclusive,
            {"candidate_ids": ["C2"]}, ready(),
            draft("Normalize iki girdide de aynı sonucu verir.", ["E1", "E2"]), review(),
        ], question="normalize eşdeğer girdilerde aynı sonucu üretir mi?")
        self.assertEqual(result.status, "review_required")
        self.assertTrue(any(
            call.get("tool") == "find_tests" and call.get("query") == "normalize"
            for call in result.tool_calls
        ))

    def test_recovery_is_bounded_after_search_and_revision(self):
        (self.root / "normalizer.py").write_text(
            "LIMIT = 12\n\ndef normalize(text):\n    return text[:LIMIT]\n",
        )
        responses = [
            plan(), {"candidate_ids": ["C1"]}, ready(),
            draft("Sınır belirsiz.", ["E1"]), review(False),
            recover("search", "LIMIT"),
            lambda data, ids: {"candidate_ids": [
                next(c["id"] for c in data["candidates"] if c["line"] == 1)
            ]},
            ready(), draft("Yanlış gerekçe ile sınır 12.", ["E1", "E2"]), review(False),
            recover("revise"), draft("Sınır 12'dir.", ["E1", "E2"]), review(False),
        ]
        result, _ = self.run_workflow(responses)
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.stages.count("RECOVER"), agent.MAX_RECOVERY_ROUNDS)
        self.assertEqual(result.stages.count("SEARCH"), 2)
        self.assertEqual(result.stages.count("REVISE"), 1)

    def test_single_revision_does_not_restart_research(self):
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, ready(),
            draft("Uydurma."), review(False), recover(), draft(), review(),
        ])
        self.assertEqual(result.status, "review_required")
        self.assertEqual(result.stages.count("SEARCH"), 1)
        self.assertEqual(result.stages.count("READ"), 1)

    def test_verify_can_return_to_research_for_a_model_selected_dependency(self):
        (self.root / "normalizer.py").write_text(
            "PAGE_LIMIT = 41\n\ndef normalize(text):\n    return text[:PAGE_LIMIT]\n",
        )
        responses = [
            plan(), {"candidate_ids": ["C1"]}, ready(),
            draft("Bir limite göre kırpar.", ["E1"]),
            {"question_checklist": [{"requested_fact": "Sınır değeri", "covered": False,
                                      "explanation": "Değer cevapta yok."}],
             "source_interpretation": "Sabitin kullanımı var ama değeri okunmadı.",
             "supported": False, "complete": False,
             "issues": ["PAGE_LIMIT tanımı ve değeri eksik."]},
            recover("search", "PAGE_LIMIT"),
            lambda data, ids: {"candidate_ids": [
                next(c["id"] for c in data["candidates"] if c["line"] == 1)
            ]},
            ready(), draft("Sınır 41'dir.", ["E1", "E2"]), review(),
        ]
        result, gateway = self.run_workflow(
            responses, question="normalize en fazla kaç karakter döndürür?",
        )
        self.assertEqual(result.status, "review_required")
        self.assertEqual(result.stages, [
            "LIST", "ROUTE", "SEARCH", "SELECT", "READ", "ASSESS",
            "DRAFT", "GROUNDING", "VERIFY", "RECOVER", "SEARCH", "SELECT", "READ",
            "ASSESS", "REDRAFT", "GROUNDING", "VERIFY", "RESULT",
        ])
        self.assertTrue(any(call.get("query") == "PAGE_LIMIT" for call in result.tool_calls))
        self.assertIn("PAGE_LIMIT", gateway.inputs[5]["search_targets"])
        self.assertEqual(
            {citation["file"] for citation in result.findings[0]["evidence"]},
            {"normalizer.py"},
        )

    def test_terminal_prints_structured_decisions_not_only_stage_names(self):
        gateway = ScriptedGateway(self.simple_responses())
        stream = io.StringIO()
        with redirect_stdout(stream):
            agent.run_agent("Fonksiyon ne yapıyor?", gateway=gateway)
        output = stream.getvalue()
        for label in ("AJAN KARARI — ROUTE", "AJAN KARARI — SELECT",
                      "KANIT DURUMU — ASSESS", "AJAN TASLAĞI",
                      "KANIT BAĞLAMA — GROUNDING", "KONTROL — VERIFY"):
            self.assertIn(label, output)

    def test_unverified_assessment_facts_are_not_printed_as_final_facts(self):
        claimed = {
            "established_facts": ["Yanlış ara model yorumu."],
            "action": "answer", "missing_information": "", "searches": [],
        }
        gateway = ScriptedGateway([
            plan(), {"candidate_ids": ["C1"]}, claimed, draft(), review(),
        ])
        stream = io.StringIO()
        with redirect_stdout(stream):
            agent.run_agent("Fonksiyon ne yapıyor?", gateway=gateway)
        self.assertNotIn("Yanlış ara model yorumu", stream.getvalue())

    def test_default_terminal_result_is_short_and_does_not_dump_source_json(self):
        gateway = ScriptedGateway(self.simple_responses())
        stream = io.StringIO()
        with redirect_stdout(stream):
            agent.run_agent("Fonksiyon ne yapıyor?", gateway=gateway)
        output = stream.getvalue()
        self.assertIn("[SONUÇ]", output)
        self.assertIn("[KANIT KONUMLARI]", output)
        self.assertIn("normalizer.py:1-2", output)
        self.assertNotIn('"findings":', output)
        self.assertNotIn('"quote":', output)

    def test_json_terminal_output_remains_available_when_explicitly_requested(self):
        gateway = ScriptedGateway(self.simple_responses())
        stream = io.StringIO()
        with redirect_stdout(stream):
            agent.run_agent("Fonksiyon ne yapıyor?", gateway=gateway, json_output=True)
        self.assertIn('"findings":', stream.getvalue())

    def test_cli_exit_code_treats_a_reviewable_answer_as_completed(self):
        self.assertEqual(agent._cli_exit_code("review_required"), 0)
        for failed in ("insufficient_evidence", "budget_exhausted", "stopped"):
            self.assertEqual(agent._cli_exit_code(failed), 1)

    def test_unsupported_number_triggers_recovery_without_llm_review_approval(self):
        gateway = ScriptedGateway([
            plan(), {"candidate_ids": ["C1"]}, ready(),
            draft("Fonksiyon 999 karakter döndürür.", ["E1"]), recover("stop"),
        ])
        stream = io.StringIO()
        with redirect_stdout(stream):
            result = agent.run_agent("Fonksiyon ne yapıyor?", gateway=gateway)
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertIn("999", result.reason)
        self.assertNotIn("VERIFY", result.stages)
        self.assertIn("KANIT BAĞLAMA — GROUNDING", stream.getvalue())

    def test_requested_condition_must_preserve_the_observed_predicate(self):
        (self.root / "normalizer.py").write_text(
            "SKIP = {'tmp'}\n\ndef visible(name):\n"
            "    return not name.startswith('.') and name not in SKIP\n",
            encoding="utf-8",
        )
        store = agent.EvidenceStore()
        candidate = store.search(
            agent.SearchRequest(tool="find_symbol", query="visible"),
        )[0]
        store.read(candidate)
        bad = agent.Draft.model_validate(draft("SKIP içindekiler alınmaz.", ["E1"]))
        self.assertTrue(agent._condition_grounding_issues(
            bad, store, "visible hangi koşulla isimleri seçer?",
        ))

    def test_missing_condition_is_revised_without_new_repository_search(self):
        (self.root / "normalizer.py").write_text(
            "def normalize(text):\n    return text if text is not None else ''\n",
            encoding="utf-8",
        )
        bad_draft = draft("None değerinde boş metin döner.", ["E1"])
        exact_draft = draft(
            "Koşul `text is not None` ifadesidir; doğruysa text, değilse boş metin döner.",
            ["E1"],
        )
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, ready(), bad_draft, exact_draft, review(),
        ], question="normalize hangi koşulla text değerini döndürür?")
        self.assertEqual(result.status, "review_required")
        self.assertEqual(
            [call["tool"] for call in result.tool_calls],
            ["list_files", "find_symbol", "read_file"],
        )

    def test_reviewer_checks_original_question_not_only_model_plan(self):
        question = "İşlevi ve geri dönüş değerini ayrı ayrı açıkla."
        result, gateway = self.run_workflow(self.simple_responses(), question=question)
        self.assertEqual(gateway.inputs[-1]["question"], question)
        self.assertNotIn("route", gateway.inputs[-1])

    def test_uncovered_question_check_cannot_be_marked_complete(self):
        contradictory_review = review(True)
        contradictory_review["question_checklist"][0]["covered"] = False
        contradictory_review["question_checklist"][0]["explanation"] = "Kullanım yeri yok."
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, ready(), draft(),
            contradictory_review, recover("stop"),
        ], question="Tanımı ve kullanım yerini açıkla.")
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertIn("Sorunun bu kısmı cevaplanmadı", result.reason)

    def test_reading_unrelated_constant_does_not_force_a_lookup(self):
        (self.root / "normalizer.py").write_text(
            "def normalize(text):\n    if text is None:\n        return None\n"
            "    return text[:UNRELATED_CAP]\n",
        )
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, ready(),
            draft("None geldiğinde None döner.", ["E1"]), review(),
        ], question="Girdi None olduğunda ne olur?")
        self.assertEqual(result.status, "review_required")
        self.assertEqual(sum(c["tool"] == "find_symbol" for c in result.tool_calls), 1)
        self.assertFalse(any(c["tool"] == "search_code" for c in result.tool_calls))

    def test_new_dependency_search_is_chosen_by_model_and_cited_separately(self):
        (self.root / "normalizer.py").write_text(
            "def normalize(text):\n    return text[:BATCH_SIZE]\n",
        )
        (self.root / "settings.py").write_text("BATCH_SIZE = 23\n")
        responses = [
            plan(), {"candidate_ids": ["C1"]},
            {"established_facts": [], "action": "search", "missing_information": "Sabitin değeri.",
             "searches": [{"tool": "search_code", "query": "BATCH_SIZE"}]},
            lambda data, ids: {"candidate_ids": [
                next(c["id"] for c in data["candidates"] if c["file"] == "settings.py")
            ]},
            ready(), draft("Sınır 23.", ["E1", "E2"]), review(),
        ]
        result, _ = self.run_workflow(responses)
        self.assertEqual(result.status, "review_required")
        self.assertEqual({c["file"] for c in result.findings[0]["evidence"]},
                         {"normalizer.py", "settings.py"})

    def test_repeat_search_does_not_execute_again_or_loop_forever(self):
        repeat = {"established_facts": [], "action": "search", "missing_information": "Bulunamadı.",
                  "searches": [{"tool": "find_symbol", "query": "absent"}]}
        result, _ = self.run_workflow([plan("absent")] + [repeat] * agent.MAX_RESEARCH_ROUNDS)
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(len(result.tool_calls), 2)  # list + tek search
        self.assertEqual(result.findings, [])

    def test_changed_file_before_publish_stops_answer(self):
        def mutate(data, ids):
            (self.root / "normalizer.py").write_text("def normalize(text):\n    return None\n")
            return review()
        result, _ = self.run_workflow([
            plan(), {"candidate_ids": ["C1"]}, ready(), draft(), mutate,
        ])
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.findings, [])

    def test_next_question_has_new_evidence_store(self):
        first, _ = self.run_workflow(self.simple_responses())
        (self.root / "normalizer.py").write_text("def normalize(text):\n    return text.upper()\n")
        second, _ = self.run_workflow(self.simple_responses())
        self.assertNotEqual(first.findings[0]["evidence"][0]["quote"],
                            second.findings[0]["evidence"][0]["quote"])

    def test_bad_json_and_illegal_actions_cannot_reach_tools(self):
        gateway = ModelGateway("test", chat=lambda **kwargs: {
            "message": {"content": '{"intent":"general_code_search","entities":["x"],'
                                   '"source_policy":"code_first","requirements":["x"],'
                                   '"decision_summary":"x","searches":[{"tool":"delete","query":"x"}]}'},
        })
        with redirect_stdout(io.StringIO()):
            result = agent.run_agent("Herhangi bir soru", gateway=gateway)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.tool_calls, [{"tool": "list_files", "directory_path": "."}])


if __name__ == "__main__":
    unittest.main()
