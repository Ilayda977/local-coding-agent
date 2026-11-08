"""Summary regressions use arbitrary repositories/values, not samplemod answers."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from pydantic import ValidationError
import cli
import tools
from evidence import EvidenceStore
from repository_summary import (SummarySelection, SummaryResponse, summarize_repository,
                                introduction_ids, SourceQuote)
from summary_facts import (literal_returns, check_literal_prose, check_source_tokens,
                           symbol_inventory, check_symbol_locations)
from test_agent import ScriptedGateway


def source(text, file='module.py', start=1, id='E1'):
    return {'id': id, 'file': file, 'start_line': start,
            'end_line': start + len(text.splitlines()) - 1, 'quote': text}


class SourceFactTests(unittest.TestCase):
    def test_definitions_are_distinct_from_imports_calls_and_comments(self):
        block = source('from api import decode as parse\n# def imaginary():\n'
                       'def run():\n    return parse("decode")\n', start=30)
        inventory = symbol_inventory([block])[0]
        self.assertEqual(inventory['definitions'], [{'name': 'run', 'kind': 'def', 'line': 32}])
        self.assertIn('decode', inventory['referenced_names'])
        self.assertIn('parse', inventory['referenced_names'])
        self.assertNotIn('imaginary', inventory['referenced_names'])

    def test_complete_header_survives_truncated_docstring(self):
        block = source('def dönüştür(text: str) -> str:\n    """incomplete documentation', start=24)
        inventory = symbol_inventory([block])[0]
        self.assertEqual(inventory['definitions'], [{'name': 'dönüştür', 'kind': 'def', 'line': 24}])
        self.assertEqual(symbol_inventory([source('def unfinished(')])[0]['definitions'], [])

    def test_wrong_unquoted_function_in_one_file_is_rejected(self):
        blocks = [source('def decode(x): return x\n', file='api.py'),
                  source('def _decode_inner(x): return x\n', file='native.py'),
                  source('setup = "from api import decode"\n', file='bench.py')]
        inventory = symbol_inventory(blocks)
        for text in ('native.py dosyası decode fonksiyonunu içerir.',
                     'bench.py benchmarks decode. native.py defines decode.'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                check_symbol_locations(text, blocks[1:], inventory)
        check_symbol_locations('native.py defines _decode_inner.', blocks[1:], inventory)
        check_symbol_locations('bench.py benchmarks decode.', blocks[2:], inventory)

    def test_related_identifier_substring_is_not_the_same_function(self):
        blocks = [source('def _decode_inner(x): return x\n', file='native.py')]
        with self.assertRaises(ValueError):
            check_source_tokens('Defines `decode`.', blocks)
        check_source_tokens('Defines `_decode_inner`.', blocks)

    def test_cross_file_function_claims_need_unambiguous_sentences(self):
        blocks = [source('def decode(x): return x\n', file='api.py'),
                  source('def _decode_inner(x): return x\n', file='native.py')]
        inventory = symbol_inventory(blocks)
        with self.assertRaises(ValueError):
            check_symbol_locations('api.py and native.py define decode.', blocks, inventory)
        check_symbol_locations('api.py defines decode. native.py defines _decode_inner.', blocks, inventory)

    def test_altered_example_rejected_without_simulating_transformation(self):
        block = source('>>> escape("<node>")\n"&lt;node&gt;"\n', file='README.md')
        for answer in ('Örneğin, <node> etiketi <node&gt; olarak değiştirilir.',
                       'For example, `<node>` becomes `<node&gt;`.',
                       'Returns "invented".'):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                check_source_tokens(answer, [block])
        check_source_tokens('README says "&lt;node&gt;".', [block])

    def test_tokens_are_checked_only_against_cited_source(self):
        response = SummaryResponse(action='answer', claims=[{
            'kind': 'behavior', 'answer': 'Produces `some-value`.', 'evidence_ids': ['E1']}])
        data = {'source': [source('one', id='E1'), source('some-value', id='E2')], 'candidates': []}
        with self.assertRaises(ValueError):
            response.validate_context(data)

    def test_normal_prose_and_real_file_locations_remain_allowed(self):
        blocks = [source('def escape(text): pass', file='src/pkg/native.py')]
        for answer in ("Python'ın metin aracıdır.", 'Metni dönüştürür.',
                       '`src/pkg` içinde `native.py` vardır.', '`escape` metin alır.'):
            check_source_tokens(answer, blocks)

    def test_source_quote_copies_exact_unicode_and_escape_sequences(self):
        text = 'heading\n>>> f("İğüş\\n")\n"İğüş\\n!"\nfooter'
        quote = SourceQuote(evidence_id='E1', start_line=21, end_line=22)
        citation = quote.citation([source(text, start=20, file='README.rst')])
        self.assertEqual(citation['quote'], '>>> f("İğüş\\n")\n"İğüş\\n!"')
        self.assertEqual((citation['start_line'], citation['end_line']), (21, 22))

    def test_source_quote_rejects_unread_inverted_and_oversized_ranges(self):
        blocks = [source('x\n' * 30, start=20)]
        for kwargs in ({'evidence_id': 'E999', 'start_line': 20, 'end_line': 21},
                       {'evidence_id': 'E1', 'start_line': 19, 'end_line': 21},
                       {'evidence_id': 'E1', 'start_line': 20, 'end_line': 50},
                       {'evidence_id': 'E1', 'start_line': 22, 'end_line': 21},
                       {'evidence_id': 'E1', 'start_line': 20, 'end_line': 32}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SourceQuote(**kwargs).citation(blocks)
        with self.assertRaises(ValidationError):
            SourceQuote(evidence_id='E1', start_line=True, end_line=2)

    def test_model_cannot_author_source_quote_contents(self):
        with self.assertRaises(ValidationError):
            SourceQuote(evidence_id='E1', start_line=1, end_line=1, quote='fake output')

    def test_stop_or_read_cannot_publish_examples(self):
        for action in ('read', 'stop'):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                SummaryResponse(action=action, candidate_ids=['C1'] if action == 'read' else [],
                                source_quotes=[SourceQuote(evidence_id='E1', start_line=1, end_line=1)])

    def test_exact_strings_unicode_bool_and_none(self):
        for expression in ("'merhaba… İğüş'", "'ready...!  '", 'True', 'None', '23'):
            with self.subTest(expression=expression):
                facts = literal_returns([source(f'def message():\n    return {expression}\n', start=41)])
                self.assertEqual(facts[0]['expression'], expression)
                self.assertEqual(facts[0]['line'], 42)
                self.assertEqual(facts[0]['statement'], 'return ' + expression)

    def test_docstring_is_not_a_value(self):
        facts = literal_returns([source('def message():\n    """not the result"""\n    return "actual"\n')])
        self.assertEqual([f['expression'] for f in facts], ['"actual"'])

    def test_dynamic_conditional_decorated_async_and_partial_are_not_guessed(self):
        examples = [
            'def f():\n    return helper()\n',
            'def f(x):\n    if x:\n        return "a"\n    return "b"\n',
            '@wrapper\ndef f():\n    return "a"\n',
            'async def f():\n    return "a"\n',
            'def f():\n    if condition:\n',
            'def f():\n    print("a")\n',
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(literal_returns([source(text)]), [])

    def test_only_read_python_sources_are_analyzed_and_duplicates_removed(self):
        block = source('def f():\n    return "a"\n')
        self.assertEqual(len(literal_returns([block, dict(block, id='E2')])), 1)
        self.assertEqual(literal_returns([dict(block, file='README.md')]), [])

    def test_wrong_quoted_value_is_rejected_in_turkish_and_english(self):
        facts = literal_returns([source('def message():\n    return "ready..."\n')])
        for answer in ("message 'ready' döndürür.", 'message returns `ready`.',
                       'message “not the result” döndürür.'):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                check_literal_prose(answer, ['E1'], facts)
        check_literal_prose('message returns "ready...".', ['E1'], facts)

    def test_checks_only_linked_function_evidence(self):
        facts = literal_returns([source('def message():\n    return "ready..."\n')])
        check_literal_prose('unrelated returns "other".', ['E1'], facts)
        check_literal_prose('message returns "other".', ['E2'], facts)

    def test_literal_value_is_not_regenerated_by_model(self):
        blocks = [source('def message():\n    return "İğüş..."\n')]
        facts = literal_returns(blocks)
        data = {'source': blocks, 'candidates': [], 'literal_returns': facts, 'can_read_more': False}
        SummaryResponse(action='answer', literal_return_ids=['R1']).validate_context(data)
        with self.assertRaises(ValueError):
            SummaryResponse(action='answer', literal_return_ids=['R999']).validate_context(data)


class SummaryWorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        root_patch = patch.object(tools, 'PROJECT_ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        (self.root / 'engine.py').write_text('def message():\n    return "İğüş..."\n', encoding='utf-8')

    def test_selection_needs_introduction_and_implementation(self):
        candidates = [
            {'id': 'C1', 'file': 'README.md', 'role': 'documentation'},
            {'id': 'C2', 'file': 'engine.py', 'role': 'implementation'},
            {'id': 'C3', 'file': 'docs/README.md', 'role': 'documentation'},
        ]
        self.assertEqual(introduction_ids(candidates), {'C1'})
        for ids in (['C1'], ['C2'], ['C2', 'C3']):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                SummarySelection(candidate_ids=ids, reason='Select').validate_context({'candidates': candidates})
        SummarySelection(candidate_ids=['C1', 'C2'], reason='Select').validate_context({'candidates': candidates})
        schema = SummarySelection.constrain_schema(SummarySelection.model_json_schema(), {'candidates': candidates})
        self.assertEqual(len(schema['properties']['candidate_ids']['allOf']), 2)

    def test_no_readme_does_not_prevent_code_overview(self):
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1'], 'reason': 'Read source.'},
            {'action': 'answer', 'literal_return_ids': ['R1']},
        ])
        result = summarize_repository('Özetle.', gateway)
        self.assertEqual(result['status'], 'review_required')
        self.assertIn('return "İğüş..."', result['findings'][0]['answer'])
        self.assertTrue(any('README' in text for text in result['limitations']))

    def test_unquoted_wrong_file_function_claim_is_not_published(self):
        (self.root / 'api.py').write_text('def decode(x): return x\n')
        (self.root / 'native.py').write_text('def _decode_inner(x): return x\n')
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1', 'C3'], 'reason': 'Read public API and helper.'},
            {'action': 'answer', 'claims': [{'kind': 'behavior', 'evidence_ids': ['E2'],
                 'answer': 'native.py defines decode.'}]},
        ])
        result = summarize_repository('Temel dosyaları özetle.', gateway)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['findings'], [])
        observed = gateway.inputs[-1]['observed_symbols']
        self.assertEqual(observed[0]['definitions'][0]['name'], 'decode')
        self.assertEqual(observed[1]['definitions'][0]['name'], '_decode_inner')

    def test_source_example_is_rendered_from_read_registry_not_model_text(self):
        (self.root / 'README.md').write_text('Example\n>>> format_name("abc")\n"ABC"\n')
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1', 'C2'], 'reason': 'Read docs and implementation.'},
            {'action': 'answer', 'source_quotes': [{'evidence_id': 'E1', 'start_line': 2, 'end_line': 3}]},
        ])
        result = summarize_repository('Kaynakta varsa bir örnek göster.', gateway)
        self.assertEqual(result['status'], 'review_required')
        finding = result['findings'][0]
        self.assertEqual(finding['kind'], 'source_quote')
        self.assertEqual(finding['evidence'][0]['quote'], '>>> format_name("abc")\n"ABC"')
        self.assertIn(finding['evidence'][0]['quote'], finding['answer'])

    def test_original_markup_failure_does_not_reach_output(self):
        (self.root / 'README.md').write_text('>>> escape("<node>")\n"&lt;node&gt;"\n')
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1', 'C2'], 'reason': 'Read docs and implementation.'},
            {'action': 'answer', 'claims': [{'kind': 'behavior', 'evidence_ids': ['E1'],
                 'answer': 'Örneğin, <node> etiketi <node&gt; olarak değiştirilir.'}]},
        ])
        result = summarize_repository('Özetle.', gateway)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['findings'], [])

    def test_purpose_claim_requires_purpose_source_not_just_function(self):
        claim = {'kind': 'purpose', 'answer': 'Projenin amacı mesaj basmak.', 'evidence_ids': ['E1']}
        response = SummaryResponse(action='answer', claims=[claim])
        data = {'source': [source('def f(): pass')], 'candidates': [], 'purpose_evidence_ids': []}
        with self.assertRaises(ValueError):
            response.validate_context(data)
        data['purpose_evidence_ids'] = ['E1']
        response.validate_context(data)

    def test_read_not_selected_and_literal_output_are_controller_owned(self):
        (self.root / 'README.md').write_text('A small example package.\n')
        (self.root / 'other.py').write_text('OTHER = 1\n')
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1', 'C2'], 'reason': 'Read purpose and code.'},
            {'action': 'answer', 'claims': [{'kind': 'purpose', 'answer': 'Örnek paket.', 'evidence_ids': ['E1']}],
             'literal_return_ids': ['R1']},
        ])
        result = summarize_repository('Projenin amacı ve kodu?', gateway)
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['unread_candidates'], ['other.py'])
        self.assertEqual([attempt['status'] for attempt in result['read_attempts']], ['read_excerpt'] * 2)
        self.assertNotIn('okunamadı', ' '.join(result['limitations']))
        self.assertEqual(result['findings'][1]['answer'], 'message: return "İğüş..."')
        self.assertIn('return "İğüş..."', result['findings'][1]['evidence'][0]['quote'])

    def test_failed_read_is_distinct_from_never_selected(self):
        (self.root / 'other.py').write_text('OTHER = 1\n')
        gateway = ScriptedGateway([{'candidate_ids': ['C1'], 'reason': 'Read source.'}])
        with patch.object(EvidenceStore, 'read', side_effect=PermissionError('test failure')):
            result = summarize_repository('Özetle.', gateway)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['read_attempts'][0]['status'], 'failed')
        self.assertEqual(result['unread_candidates'], ['other.py'])
        self.assertEqual(result['files_read'], [])

    def test_model_cannot_supply_read_failure_metadata(self):
        with self.assertRaises(ValidationError):
            SummaryResponse(action='answer', literal_return_ids=['R1'], limitations=['README okunamadı.'])

    def test_fabricated_literal_is_not_published(self):
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1'], 'reason': 'Read source.'},
            {'action': 'answer', 'claims': [{'kind': 'behavior',
                'answer': 'message "yanlış" döndürür.', 'evidence_ids': ['E1']}]},
        ])
        result = summarize_repository('Özetle.', gateway)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['findings'], [])

    def test_cli_json_includes_controller_read_states_and_exact_source_value(self):
        gateway = ScriptedGateway([
            {'candidate_ids': ['C1'], 'reason': 'Read source.'},
            {'action': 'answer', 'literal_return_ids': ['R1']},
        ])
        output = io.StringIO()
        with patch.object(cli, 'ModelGateway', return_value=gateway), redirect_stdout(output):
            code = cli.main(['--repo', str(self.root), '--summary', '--json'])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload['read_attempts'][0]['status'], 'read_excerpt')
        self.assertEqual(payload['findings'][0]['answer'], 'message: return "İğüş..."')


if __name__ == '__main__':
    unittest.main()
