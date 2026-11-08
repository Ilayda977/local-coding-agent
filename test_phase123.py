"""End-to-end controller regressions using scripted models, not answer quality tests."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import agent
import cli
import tools
from evidence import EvidenceStore, EvidenceError
from protocol import EvidenceCheck, SearchRequest
from patching import prepare_patch, apply_patch, rollback, PatchError
from patch_journal import save_receipt, load_receipt
from patch_workflow import propose_patch, preview_payload, restore_preview
from repository_summary import summarize_repository, repository_inventory
from test_agent import ScriptedGateway, plan, ready, draft, review
from test_patch_protocol import proposal


class Phase123Tests(unittest.TestCase):
    def test_explicit_identifier_is_not_shadowed_by_prose_search(self):
        from research_routing import initial_searches
        from protocol import RouteDecision
        route = RouteDecision.model_validate(plan('wrong'))
        route.searches = [SearchRequest(tool='search_code', query='walk results')]
        requests = initial_searches('list_files os.walk sonuçlarını mı filtreler?', route, route.searches)
        self.assertEqual((requests[0].tool, requests[0].query), ('find_symbol', 'list_files'))

    def test_real_line_reference_is_not_treated_as_a_constant_value(self):
        from citation_checks import without_verified_locations
        self.assertEqual(without_verified_locations('qwen3.5:4b', []), ('qwen3.5:4b', []))
        self.file.write_text('\n' * 13 + 'LIMIT = 50\n')
        store = EvidenceStore()
        store.read(store.search(SearchRequest(tool='find_symbol', query='LIMIT'))[0])
        for answer in ('LIMIT 14. satırda; değeri 50.', 'normalizer.py:14 içinde 50.',
                       'LIMIT line 14; value 50.'):
            with self.subTest(answer=answer):
                candidate = agent.Draft.model_validate(draft(answer))
                self.assertEqual(agent._numeric_grounding_issues(candidate, store, ''), [])
        for answer in ('Değeri 14.', 'LIMIT satır 999 içinde.', 'normalizer.py:999 içinde 50.'):
            with self.subTest(answer=answer):
                candidate = agent.Draft.model_validate(draft(answer))
                self.assertTrue(agent._numeric_grounding_issues(candidate, store, ''))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.root_patch = patch.object(tools, 'PROJECT_ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.file = self.root / 'normalizer.py'
        self.file.write_text('def normalize(text):\n    return text.strip()\n', encoding='utf-8')

    def evidence(self, budget=16000):
        store = EvidenceStore(max_chars=budget)
        ids = store.search(SearchRequest(tool='find_symbol', query='normalize'))
        store.read(ids[0])
        return store

    def test_failed_read_is_not_committed(self):
        store = EvidenceStore(max_chars=1)
        cid = store.search(SearchRequest(tool='find_symbol', query='normalize'))[0]
        with self.assertRaises(EvidenceError):
            store.read(cid)
        self.assertFalse(store.is_read(cid))
        self.assertFalse(store.lines)
        self.assertFalse(store.file_hashes)

    def test_unrelated_same_name_constant_is_not_a_dependency(self):
        self.file.write_text('def normalize(text):\n    return LIMIT\n')
        (self.root / 'unrelated.py').write_text('LIMIT = 123\n')
        store = self.evidence()
        check = EvidenceCheck(requested_fact='Değer?', observed_answer='LIMIT',
                              evidence_ids=['E1'], status='supported')
        self.assertEqual(store.unread_claim_values([check]), [])

    def test_imported_alias_definition_is_a_dependency(self):
        self.file.write_text('from settings import LIMIT as CAP\ndef normalize(text):\n    return CAP\n')
        (self.root / 'settings.py').write_text('LIMIT = 23\n')
        (self.root / 'unrelated.py').write_text('CAP = 999\n')
        store = self.evidence()
        check = EvidenceCheck(requested_fact='Değer?', observed_answer='CAP',
                              evidence_ids=['E1'], status='supported')
        candidates = store.unread_claim_values([check])
        self.assertEqual([store.candidates[c].file for c in candidates], ['settings.py'])

    def test_qualified_reference_search(self):
        self.file.write_text('def normalize(text):\n    return text.strip()\n')
        self.assertIn('normalizer.py', tools.find_references('text.strip'))

    def test_annotation_without_assignment_does_not_crash_trace(self):
        self.file.write_text('def normalize(text):\n    value: int\n    return text\n')
        self.assertIsInstance(self.evidence().trace_frontier(), list)

    def test_large_directory_scan_reports_partial_listing(self):
        (self.root / 'a.py').write_text('A = 1\n')
        with patch.object(tools, 'MAX_DIRECTORY_SCAN', 1):
            self.assertIn('liste ve sayı kısmidir', tools.list_files())

    def test_summary_uses_real_citations_and_no_writes(self):
        before = self.file.read_bytes()
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1'], 'reason': 'Read implementation.'},
            {'action': 'answer', 'claims': [{'kind': 'behavior', 'answer': 'Metnin kenar boşluklarını temizler.',
                 'evidence_ids': ['E1']}], 'candidate_ids': []},
        ])
        result = summarize_repository('Bu projeyi özetle.', gateway)
        self.assertEqual(result['status'], 'review_required')
        citation = result['findings'][0]['evidence'][0]
        self.assertEqual(citation['file'], 'normalizer.py')
        self.assertIn('text.strip()', citation['quote'])
        self.assertEqual(before, self.file.read_bytes())

    def test_summary_controller_policy_is_not_passed_as_repository_evidence(self):
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1'], 'reason': 'Read implementation.'},
            {'action': 'answer', 'claims': [{'kind': 'behavior', 'answer': 'Trims whitespace.',
                 'evidence_ids': ['E1']}]},
        ])
        result = summarize_repository('Summarize.', gateway)
        self.assertIn('excluded_directories', result['inventory'])
        for data in gateway.inputs:
            self.assertNotIn('inventory', data)
            self.assertNotIn('excluded_directories', data)
        self.assertIn('text.strip()', json.dumps(gateway.inputs[-1]['source']))

    def test_summary_invented_citation_fails_closed(self):
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1'], 'reason': 'Read.'},
            {'action': 'answer', 'claims': [{'kind': 'behavior', 'answer': 'Invented.', 'evidence_ids': ['E999']}],
             'candidate_ids': []},
        ])
        result = summarize_repository('Summarize.', gateway)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertFalse(result['findings'])

    def test_summary_cannot_claim_overview_after_selecting_only_docs(self):
        from repository_summary import SummarySelection, source_role
        selection = SummarySelection(candidate_ids=['C1'], reason='Read docs only.')
        with self.assertRaises(ValueError):
            selection.validate_context({'candidates': [
                {'id': 'C1', 'role': 'documentation'}, {'id': 'C2', 'role': 'implementation'}]})
        self.assertEqual(source_role('docs/conf.py'), 'documentation')
        self.assertEqual(source_role('sample/core.py'), 'implementation')

    def test_inventory_skips_symlinks_and_is_explicitly_bounded(self):
        (self.root / 'linked.py').symlink_to(self.file)
        (self.root / '.env').write_text('SECRET=not-for-model\n')
        inv = repository_inventory()
        self.assertEqual([c['file'] for c in inv['candidates']], ['normalizer.py'])
        self.assertFalse(repository_inventory(max_entries=1)['complete'])

    def test_patch_workflow_is_preview_only_and_rejects_unknown_source(self):
        store = self.evidence()
        change_plan = {'status': 'proposed', 'changes': [{'file': 'normalizer.py'}]}
        edit = {'evidence_id': 'E1', 'old_text': 'return text.strip()', 'new_text': 'return text.lstrip()'}
        before = self.file.read_bytes()
        preview = propose_patch('Trim left only.', change_plan, store, ScriptedGateway([edit]))
        self.assertEqual(before, self.file.read_bytes())
        self.assertEqual(restore_preview(preview_payload(preview)), preview)
        edit['evidence_id'] = 'E999'
        with self.assertRaises(ValueError):
            propose_patch('Trim left only.', change_plan, store, ScriptedGateway([edit]))

    def test_plan_does_not_inherit_an_incorrect_diagnosis_as_desired_behavior(self):
        from patch_protocol import propose_change
        gateway = ScriptedGateway([proposal()])
        question = 'Trim only the left side.'
        propose_change(question, [{'answer': 'WRONG: preserve both-side trimming.', 'evidence': []}],
                       self.evidence(), gateway)
        self.assertEqual(gateway.inputs[0]['question'], question)
        self.assertNotIn('WRONG', json.dumps(gateway.inputs[0]))
        self.assertTrue(gateway.inputs[0]['source'])

    def test_patch_generation_from_diagnosis_never_writes(self):
        gateway = ScriptedGateway([plan(), {'candidate_ids': ['C1']}, ready(), draft(), review(),
            proposal(), {'evidence_id': 'E1', 'old_text': 'return text.strip()',
                         'new_text': 'return text.lstrip()'}])
        before = self.file.read_bytes()
        with redirect_stdout(io.StringIO()):
            result = agent.run_agent('normalize sadece sol boşlukları temizlesin.', gateway=gateway,
                                     patch_changes=True)
        self.assertEqual(result.status, 'review_required')
        self.assertIn('+    return text.lstrip()', result.patch_preview['diff'])
        self.assertEqual(before, self.file.read_bytes())

    def test_noop_patch_preserves_plan_and_exposes_failure(self):
        gateway = ScriptedGateway([plan(), {'candidate_ids': ['C1']}, ready(), draft(), review(),
            proposal(), {'evidence_id': 'E1', 'old_text': 'return text.strip()',
                         'new_text': 'return text.strip()'}])
        output = io.StringIO()
        with redirect_stdout(output):
            result = agent.run_agent('normalize değişikliğini öner.', gateway=gateway, patch_changes=True)
        self.assertEqual(result.status, 'patch_unavailable')
        self.assertEqual(result.change_plan['status'], 'proposed')
        self.assertIsNone(result.patch_preview)
        self.assertIn('PATCH ÜRETİLEMEDİ', output.getvalue())

    def test_journal_roundtrip_and_stale_rollback(self):
        before = self.file.read_bytes()
        preview = prepare_patch(self.root, 'normalizer.py', 'text.strip()', 'text.lstrip()')
        receipt = apply_patch(preview, preview.approval_id)
        path = save_receipt(receipt)
        self.addCleanup(path.unlink, missing_ok=True)
        restored = load_receipt(path)
        rollback(restored, restored.rollback_id)
        self.assertEqual(before, self.file.read_bytes())
        apply_patch(preview, preview.approval_id)
        self.file.write_text('USER_EDIT = True\n')
        with self.assertRaises(PatchError):
            rollback(restored, restored.rollback_id)
        self.assertEqual(self.file.read_text(), 'USER_EDIT = True\n')

    def test_cli_refuses_automatic_approval(self):
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaises(PatchError):
                cli.confirm('APPLY-token', input_fn=lambda _: 'APPLY-token')
        with patch('sys.stdin.isatty', return_value=True):
            with self.assertRaises(PatchError):
                cli.confirm('APPLY-token', input_fn=lambda _: '')

    def test_cli_has_single_json_result_and_restores_root(self):
        output = io.StringIO()
        def runner(question, **kwargs):
            self.assertTrue(kwargs['json_output'])
            print(json.dumps({'status': 'review_required'}))
            return agent.AgentResult('review_required', question)
        with redirect_stdout(output):
            code = cli.main(['--repo', str(self.root), '--json', 'A question'], runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'review_required')
        self.assertEqual(tools.PROJECT_ROOT, self.root)

    def test_terminal_diff_cannot_contain_escape_codes(self):
        self.assertEqual(cli.terminal_text('\x1b[2Jhidden\x08'), '\\x1b[2Jhidden\\x08')
        self.assertEqual(cli.terminal_text('Türkçe\u202e'), 'Türkçe\\u202e')

    def test_cli_apply_and_rollback_with_separate_human_approvals(self):
        before = self.file.read_bytes()
        preview = prepare_patch(self.root, 'normalizer.py', 'text.strip()', 'text.lstrip()')
        def runner(question, **kwargs):
            self.assertTrue(kwargs['patch_changes'])
            return agent.AgentResult('review_required', question, patch_preview=preview_payload(preview))
        saved = []
        def save(receipt):
            path = save_receipt(receipt)
            saved.append(path)
            self.addCleanup(path.unlink, missing_ok=True)
            return path
        with patch('sys.stdin.isatty', return_value=True), \
             patch('builtins.input', return_value=preview.approval_id), \
             patch('cli.save_receipt', side_effect=save), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--apply', '--repo', str(self.root), 'Trim left'], runner=runner), 0)
        self.assertIn('lstrip', self.file.read_text())
        receipt = load_receipt(saved[0])
        with patch('sys.stdin.isatty', return_value=True), \
             patch('builtins.input', return_value=receipt.rollback_id), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--rollback', str(saved[0])]), 0)
        self.assertEqual(self.file.read_bytes(), before)

    def test_cli_refuses_noninteractive_apply_before_model_call(self):
        with patch('sys.stdin.isatty', return_value=False), \
             patch('cli.ModelGateway', side_effect=AssertionError('Must not call model')), \
             redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--apply', 'Change it']), 1)

    def test_private_key_and_case_variant_metadata_cannot_be_read(self):
        (self.root / 'private.key').write_text('private')
        (self.root / '.GiT').mkdir()
        (self.root / '.GiT' / 'config').write_text('private')
        for name in ('private.key', '.GiT/config', '.ENV.production'):
            self.assertIsNone(tools._resolve_safe_path(name))

    def test_unicode_identifier_and_close_spelling_are_candidates_not_answers(self):
        self.file.write_text('def ölçüm(value):\n    return value\n')
        self.assertIn('normalizer.py', tools.find_symbol('ölçüm'))
        self.assertIn('normalizer.py', tools.find_symbol('ÖLÇÜM'))

    def test_negative_api_claim_reaches_semantic_review_not_research(self):
        self.file.write_text('def normalize(text):\n    return text.strip()\n')
        gateway = ScriptedGateway([plan(), {'candidate_ids': ['C1']}, ready(),
            draft('os.walk kullanmaz; metnin kenar boşluklarını temizler.'), review()])
        with redirect_stdout(io.StringIO()):
            result = agent.run_agent('normalize os.walk kullanır mı?', gateway=gateway)
        self.assertEqual(result.status, 'review_required')
        self.assertEqual([t['stage'] for t in gateway.trace][-1], 'VERIFY')
        self.assertTrue(gateway.inputs[-1]['non_authoritative_review_hints'])


if __name__ == '__main__':
    unittest.main()
