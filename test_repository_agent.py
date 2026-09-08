"""Controller regression checks with scripted decisions, NOT model accuracy tests."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import tools
from repository_agent import discover_candidates, run_repository_agent, target_is_read
from evidence import EvidenceStore
from protocol import ModelGateway, SearchRequest
from task_contract import TaskContract, NextAction, AnswerAudit, check_answers, AnswerItem


QUESTION = 'trim(value) sonucunu ve nedenini açıkla.'
TASK = {'target': 'trim', 'target_kind': 'symbol', 'target_user_excerpt': 'trim',
        'inputs_and_assumptions': ['value'], 'requirements': [
            {'user_excerpt': 'sonucunu ve nedenini'}]}
ANSWER = {'requirement_id': 'Q1', 'answer': 'Baş ve son boşlukları temizler.',
          'mechanism': 'return value.strip() ifadesi döndürülür.',
          'anchors': [{'evidence_id': 'E1'}]}


class FakeGateway:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.trace, self.inputs = [], []

    def ask(self, stage, model, instruction, data):
        self.trace.append({'stage': stage})
        self.inputs.append((stage, copy.deepcopy(data)))
        return model.model_validate(next(self.responses))


class ContractControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'textops.py').write_text('def trim(value):\n    return value.strip()\n')
        self.patcher = patch.object(tools, 'PROJECT_ROOT', self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def run_flow(self, responses):
        gateway = FakeGateway(responses)
        with redirect_stdout(io.StringIO()) as output:
            result = run_repository_agent(QUESTION, gateway, json_output=True)
        self.assertEqual(json.loads(output.getvalue())['status'], result['status'])
        return result, gateway

    def test_list_first_target_search_and_blind_review(self):
        result, gateway = self.run_flow([
            TASK, {'action': 'read', 'summary': 'Hedef okunuyor.', 'candidate_ids': ['C1']},
            {'action': 'answer', 'summary': 'Kanıt hazır.', 'answers': [ANSWER]},
            {'sufficient': True, 'missing': '', 'answers': [ANSWER]},
            {'checks': [{'requirement_id': 'Q1', 'agrees': True, 'explanation': 'Kaynak destekliyor.'}]},
        ])
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['tool_calls'][0]['tool'], 'list_files')
        self.assertEqual(result['tool_calls'][1]['query'], 'trim')
        blind = next(data for stage, data in gateway.inputs if stage == 'INDEPENDENT_READING')
        self.assertEqual(set(blind), {'contract', 'source', 'source_reference_index'})
        self.assertIn('return value.strip()', result['diagnosis']['root_cause'])
        self.assertIn('return value.strip()', result['diagnosis']['evidence'][0]['quote'])
        self.assertEqual(set(result['diagnosis']), {'issue_summary', 'evidence', 'root_cause', 'relevant_files', 'confidence'})

    def test_cannot_answer_before_target_read(self):
        result, _ = self.run_flow([TASK, {'action': 'answer', 'summary': 'Tahmin.', 'answers': [ANSWER]}])
        self.assertEqual(result['status'], 'stopped')
        self.assertIsNone(result['diagnosis'])

    def test_unsupported_api_is_repaired_before_model_audit(self):
        wrong = dict(ANSWER, answer='remote.fetch çağrılır.')
        result, gateway = self.run_flow([
            TASK, {'action': 'read', 'summary': 'Oku.', 'candidate_ids': ['C1']},
            {'action': 'answer', 'summary': 'Cevap.', 'answers': [wrong]},
            {'action': 'answer', 'summary': 'Kaynağa göre düzelt.', 'answers': [ANSWER]},
            {'sufficient': True, 'missing': '', 'answers': [ANSWER]},
            {'checks': [{'requirement_id': 'Q1', 'agrees': True, 'explanation': 'Destekli.'}]},
        ])
        self.assertEqual(result['status'], 'review_required')
        self.assertIn('SOURCE_CHECK', result['stages'])
        self.assertEqual(sum(s['stage'] == 'INDEPENDENT_READING' for s in gateway.trace), 1)
        repair_input = [d for s, d in gateway.inputs if s == 'INVESTIGATE'][-1]
        self.assertIn('remote.fetch', repair_input['feedback'][-1]['issues'][0])

    def test_missing_evidence_returns_to_research_with_original_contract(self):
        result, gateway = self.run_flow([
            TASK, {'action': 'read', 'summary': 'Oku.', 'candidate_ids': ['C1']},
            {'action': 'answer', 'summary': 'Cevap.', 'answers': [ANSWER]},
            {'sufficient': False, 'missing': 'İlgili bağımlılığın tanımı gerekli.', 'answers': []},
            {'action': 'search', 'summary': 'Eksik bağımlılığı ara.',
             'searches': [{'tool': 'find_symbol', 'query': 'dependency'}]},
            {'action': 'stop', 'summary': 'Kanıt yetersiz.'},
        ])
        self.assertEqual(result['status'], 'insufficient_evidence')
        contract = TaskContract.model_validate(TASK).snapshot(QUESTION)
        for stage, data in gateway.inputs:
            if 'contract' in data:
                self.assertEqual(data['contract'], contract)
        self.assertTrue(any(c.get('query') == 'dependency' for c in result['tool_calls']))

    def test_repeated_rejected_answer_is_not_reviewed_again(self):
        proposal = {'action': 'answer', 'summary': 'Cevap.', 'answers': [ANSWER]}
        result, gateway = self.run_flow([
            TASK, {'action': 'read', 'summary': 'Oku.', 'candidate_ids': ['C1']},
            proposal, {'sufficient': False, 'missing': 'Eksik tanım.', 'answers': []}, proposal,
        ])
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(sum(s['stage'] == 'INDEPENDENT_READING' for s in gateway.trace), 1)

    def test_wrong_or_missing_requirement_and_quote_rejected(self):
        data = {'contract': TaskContract.model_validate(TASK).snapshot(QUESTION),
                'source': [{'id': 'E1', 'quote': 'return value.strip()'}]}
        for update in ({'requirement_id': 'Q99'}, {'anchors': [{'evidence_id': 'E9'}]},
                       {'anchors': [{'evidence_id': 'E1', 'quote': 'return invented()'}]}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                check_answers([AnswerItem.model_validate(dict(ANSWER, **update))], data)
        with self.assertRaises(ValueError):
            check_answers([], data)
        with self.assertRaises(ValueError):
            AnswerAudit.model_validate({'checks': [{'requirement_id': 'Q2', 'agrees': True,
                                                   'explanation': 'Yanlış kapsam.'}]}).validate_context(data)

    def test_contract_rejects_invented_user_excerpt(self):
        contract = TaskContract.model_validate(dict(TASK, target_user_excerpt='invented'))
        with self.assertRaises(ValueError):
            contract.validate_context({'question': QUESTION})

    def test_contract_cannot_insert_repository_claims_as_inputs(self):
        task = TaskContract.model_validate(dict(TASK, inputs_and_assumptions=['Function lives in missing.py']))
        with self.assertRaises(ValueError):
            task.validate_context({'question': QUESTION})

    def test_requirements_are_original_words_not_generated_answers(self):
        contract = TaskContract.model_validate(TASK)
        contract.validate_context({'question': QUESTION})
        self.assertEqual(contract.snapshot(QUESTION)['requirements'][0]['requested_result'],
                         'sonucunu ve nedenini')
        invalid = dict(TASK, requirements=[{'user_excerpt': 'sonucunu ve nedenini',
                                           'requested_result': 'Invented answer'}])
        with self.assertRaises(ValueError):
            TaskContract.model_validate(invalid)

    def test_answer_schema_selects_ids_without_model_written_quotes(self):
        schema = AnswerItem.model_json_schema()
        self.assertEqual(set(schema['$defs']['Anchor']['properties']), {'evidence_id'})

    def test_contract_receives_real_definition_candidates_without_body_read(self):
        result, gateway = self.run_flow([TASK, {'action': 'stop', 'summary': 'Keşif kontrolü.'}])
        data = gateway.inputs[0][1]
        self.assertEqual(gateway.inputs[0][0], 'CONTRACT')
        self.assertTrue(any(c['scope'] == 'trim' for c in data['entry_candidates']))
        self.assertTrue(data['discovery_observations'])
        self.assertFalse(any(c['tool'] == 'read_file' for c in result['tool_calls']))
        self.assertNotIn('CONTRACT_CHECK', [s['stage'] for s in gateway.trace])
        self.assertEqual(sum(c.get('query') == 'trim' for c in result['tool_calls']), 1)

    def test_discovery_does_not_turn_external_api_into_a_definition(self):
        store = EvidenceStore()
        discover_candidates('Does trim use external_api.walk?', store)
        self.assertTrue(any(c.scope == 'trim' for c in store.candidates.values()))
        external = next(c for c in store.tool_calls if c['query'] == 'external_api.walk')
        self.assertEqual(external['matched_count'], 0)
        self.assertEqual(store.blocks, {})

    def test_discovery_is_bounded_and_case_variants_remain_candidates(self):
        store = EvidenceStore()
        result = discover_candidates('Does TRIM(value) work alpha beta gamma delta epsilon?', store, limit=3)
        self.assertLessEqual(len(store.tool_calls), 3)
        self.assertGreater(result['tokens_omitted'], 0)
        self.assertTrue(any(c.scope == 'trim' for c in store.candidates.values()))

    def test_gateway_reports_actual_validation_failure(self):
        from protocol import ProtocolError
        invalid = dict(TASK, target_user_excerpt='invented')
        gateway = ModelGateway('fake', chat=lambda **kwargs: {'message': {'content': json.dumps(invalid)}})
        with self.assertRaisesRegex(ProtocolError, 'CONTRACT:.*exact substrings'):
            gateway.ask('CONTRACT', TaskContract, 'Extract scope.', {'question': QUESTION})

    def test_gateway_repairs_invalid_contract_without_extra_stdout(self):
        calls = []
        def chat(**kwargs):
            calls.append(kwargs)
            payload = dict(TASK, target_user_excerpt='invented') if len(calls) == 1 else TASK
            return {'message': {'content': json.dumps(payload)}}
        gateway = ModelGateway('fake', chat=chat)
        with redirect_stdout(io.StringIO()) as output:
            result = gateway.ask('CONTRACT', TaskContract, 'Extract scope.', {'question': QUESTION})
        self.assertEqual(result.target, 'trim')
        self.assertEqual(len(calls), 2)
        self.assertEqual(output.getvalue(), '')

    def test_action_grammar_excludes_answer_before_subject_read(self):
        data = {'contract': TaskContract.model_validate(TASK).snapshot(QUESTION),
                'source': [], 'candidates': [{'id': 'C1'}], 'target_read': False}
        schema = NextAction.constrain_schema(NextAction.model_json_schema(), data)
        self.assertNotIn('answer', schema['properties']['action']['enum'])
        self.assertEqual(schema['properties']['candidate_ids']['items']['enum'], ['C1'])
        self.assertEqual(schema['$defs']['AnswerItem']['properties']['requirement_id']['enum'], ['Q1'])

    def test_unrelated_function_does_not_count_as_subject(self):
        (self.root / 'other.py').write_text('def unrelated(value):\n    return value\n')
        store = EvidenceStore()
        store.read(store.search(SearchRequest(tool='find_symbol', query='unrelated'))[0])
        contract = TaskContract.model_validate(TASK).snapshot(QUESTION)
        self.assertFalse(target_is_read(contract, store))
        store.read(store.search(SearchRequest(tool='find_symbol', query='trim'))[0])
        self.assertTrue(target_is_read(contract, store))

    def test_repeated_search_and_unknown_candidate_rejected(self):
        data = {'previous_searches': [{'tool': 'find_symbol', 'query': 'trim'}], 'candidates': []}
        for action in ({'action': 'search', 'summary': 'Tekrar.', 'searches': [{'tool': 'find_symbol', 'query': 'trim'}]},
                       {'action': 'read', 'summary': 'Hayali.', 'candidate_ids': ['C99']}):
            with self.assertRaises(ValueError):
                NextAction.model_validate(action).validate_context(data)


if __name__ == '__main__':
    unittest.main()
