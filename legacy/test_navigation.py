"""Navigation contract regressions. These do not measure real-model accuracy."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools
from navigation import validate_target, reject_repeated_searches, symbol_match_rank
from protocol import SearchRequest


class NavigationTests(unittest.TestCase):
    def test_literal_search_is_language_independent(self):
        for literal in ('HATA: Dosya bulunamadı', 'Error: missing file', 'nasıl', 'hata_mesaji'):
            self.assertEqual(SearchRequest(tool='search_code', query=literal).query, literal)

    def test_file_cannot_be_mistaken_for_qualified_symbol(self):
        for filename in ('agent.py', 'AGENT.PY', 'src/agent.py', 'README.md'):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                validate_target('find_symbol', filename)
        self.assertEqual(validate_target('find_file', 'agent.py'), 'agent.py')
        self.assertEqual(validate_target('find_symbol', 'Gateway.request'), 'Gateway.request')

    def test_repeated_literal_query_is_case_insensitive(self):
        with self.assertRaises(ValueError):
            reject_repeated_searches([SearchRequest(tool='search_code', query='WIDTH')],
                                     [{'tool': 'search_code', 'query': 'width'}])
        reject_repeated_searches([SearchRequest(tool='find_symbol', query='Width')],
                                 [{'tool': 'find_symbol', 'query': 'width'}])

    def test_short_or_unrelated_names_are_not_fuzzy_matches(self):
        self.assertIsNone(symbol_match_rank('cat', 'bat'))
        self.assertIsNone(symbol_match_rank('render_document', 'authenticate'))

    def test_symbol_suggestions_preserve_actual_source_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'sample.py').write_text('def calculate_total():\n    return 0\n', encoding='utf-8')
            with patch.object(tools, 'PROJECT_ROOT', root):
                for query in ('CALCULATE_TOTAL', 'calcluate_total'):
                    result = tools.find_symbol(query)
                    self.assertIn('yalnız aday', result)
                    self.assertIn('sample.py (Satır 1): def calculate_total()', result)
                exact = tools.find_symbol('calculate_total')
                self.assertNotIn('Tam sembol eşleşmesi yok', exact)

    def test_exact_symbol_wins_over_case_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'sample.py').write_text('def Foo():\n    pass\ndef foo():\n    pass\n')
            with patch.object(tools, 'PROJECT_ROOT', root):
                result = tools.find_symbol('Foo')
                self.assertIn('def Foo()', result)
                self.assertNotIn('def foo()', result)

