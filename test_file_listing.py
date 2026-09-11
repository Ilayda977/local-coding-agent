"""File patterns and grounded listing; no network or live LLM."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import agent
import tools


class FileListingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'repo'
        self.root.mkdir()
        root_patch = patch.object(tools, 'PROJECT_ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        for name in ('sample/a.py', 'sample/b.py', 'sample/deep/c.py', 'sample/note.txt',
                     'root.py', '.hidden.py', 'sample/.secret.py', '.git/hidden.py', 'venv/no.py'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('x = 1\n')

    def test_star_does_not_cross_directory_boundary(self):
        self.assertEqual(tools.find_file_matches('sample/*.py')['files'], ['sample/a.py', 'sample/b.py'])
        self.assertEqual(tools.find_file_matches('*.py')['files'], ['root.py'])

    def test_double_star_includes_zero_or_more_directories(self):
        self.assertEqual(tools.find_file_matches('sample/**/*.py')['files'],
                         ['sample/a.py', 'sample/b.py', 'sample/deep/c.py'])
        self.assertEqual(tools.find_file_matches('**/*.py')['total_matches'], 4)

    def test_question_mark_character_class_and_local_directory(self):
        self.assertEqual(tools.find_file_matches('sample/[ab].py')['total_matches'], 2)
        self.assertEqual(tools.find_file_matches('?.py', 'sample')['files'], ['sample/a.py', 'sample/b.py'])

    def test_exact_filename_compatibility_and_no_match(self):
        self.assertIn('sample/a.py (Satır 1)', tools.find_file('a.py'))
        self.assertEqual(tools.find_file_matches('A.PY')['files'], ['sample/a.py'])
        self.assertEqual(tools.find_file_matches('absent/*.py')['files'], [])

    def test_unsafe_patterns_are_rejected(self):
        for query in ('../*.py', '/tmp/*.py', 'sample/../../*.py', 'C:\\outside\\*.py',
                      '~/secret/*', 'sample/\x00.py', '**/../*.py'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                tools.find_file_matches(query)
        self.assertTrue(tools.find_file('../*.py').startswith('HATA:'))

    def test_outside_symlinks_are_not_results(self):
        outside = self.root.parent / 'outside.py'
        outside.write_text('secret = 1\n')
        (self.root / 'sample' / 'escape.py').symlink_to(outside)
        (self.root / 'sample' / 'external').symlink_to(self.root.parent, target_is_directory=True)
        result = tools.find_file_matches('**/*.py')
        self.assertNotIn('sample/escape.py', result['files'])
        self.assertEqual(result['total_matches'], 4)

    def test_limit_is_not_reported_as_complete_list(self):
        with patch.object(tools, 'MAX_SEARCH_RESULTS', 2):
            result = tools.find_file_matches('**/*.py')
        self.assertEqual(len(result['files']), 2)
        self.assertEqual(result['total_matches'], 4)
        self.assertTrue(result['truncated'])

    def run_listing(self, query):
        class Gateway:
            trace = []
            def ask(self, stage, model, instruction, data, **kwargs):
                self.trace.append({'stage': stage})
                if stage != 'ROUTE':
                    raise AssertionError('A file list must not ask a model to invent the result.')
                return model.model_validate({
                    'intent': 'list_files', 'source_policy': 'code_only', 'entities': ['sample'],
                    'requirements': ['Dosya isimlerini listele.'],
                    'searches': [{'tool': 'find_file', 'query': query}],
                    'decision_summary': 'İstenen klasörde dosya adlarını ara.'})
        gateway = Gateway()
        with redirect_stdout(io.StringIO()) as output:
            result = agent.run_agent('sample klasöründeki Python dosyalarını listele.', gateway, json_output=True)
        payload = json.loads(output.getvalue())
        return result, payload

    def test_listing_is_generated_from_files_not_model_prose(self):
        result, payload = self.run_listing('sample/*.py')
        self.assertEqual(result.status, 'files_listed')
        self.assertEqual(payload['file_searches'][0]['files'], ['sample/a.py', 'sample/b.py'])
        self.assertIsNone(result.diagnosis)
        self.assertEqual([call['tool'] for call in result.tool_calls], ['list_files', 'find_file'])
        self.assertEqual(len(result.model_trace), 1)

    def test_empty_listing_does_not_read_unrelated_file(self):
        result, payload = self.run_listing('missing/*.py')
        self.assertEqual(result.status, 'files_listed')
        self.assertEqual(payload['file_searches'][0]['total_matches'], 0)
        self.assertNotIn('READ', result.stages)


if __name__ == '__main__':
    unittest.main()
