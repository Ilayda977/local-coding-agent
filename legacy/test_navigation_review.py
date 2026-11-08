"""Modelsiz regresyonlar; modelin semantik doğruluğunu ölçmez."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools
from protocol import SearchRequest


class QualifiedNavigationTests(unittest.TestCase):
    def test_qualification_survives_schema_validation(self):
        for tool in ('find_symbol', 'find_calls', 'find_references'):
            self.assertEqual(SearchRequest(tool=tool, query='Service.send').query,
                             'Service.send')

    def test_module_qualification_does_not_select_other_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'pkg').mkdir()
            (root / 'pkg' / 'service.py').write_text('def send():\n    return 17\n')
            (root / 'other.py').write_text('def send():\n    return 99\n')
            with patch.object(tools, 'PROJECT_ROOT', root):
                for query in ('service.send', 'pkg.service.send'):
                    result = tools.find_symbol(query)
                    self.assertIn('pkg/service.py (Satır 1)', result)
                    self.assertNotIn('other.py', result)

    def test_class_and_call_scope_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'app.py').write_text(
                'class First:\n    def send(self):\n        pass\n'
                'class Second:\n    def send(self):\n        pass\n'
                'first.send()\nsecond.send()\n')
            with patch.object(tools, 'PROJECT_ROOT', root):
                result = tools.find_symbol('First.send')
                self.assertIn('(Satır 2)', result)
                self.assertNotIn('(Satır 5)', result)
                calls = tools.find_calls(SearchRequest(tool='find_calls', query='first.send').query)
                self.assertIn('first.send()', calls)
                self.assertNotIn('second.send()', calls)
