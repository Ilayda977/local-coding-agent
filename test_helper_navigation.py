"""Repository helper suggestions are locators, not assumed runtime facts."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tools
from evidence import EvidenceStore
from protocol import SearchRequest, EvidenceCheck


class HelperNavigationTests(unittest.TestCase):
    def test_claimed_local_helper_requires_real_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'app.py').write_text(
                'def entry():\n    return helper()\ndef helper():\n    return 17\n')
            with patch.object(tools, 'PROJECT_ROOT', root):
                store = EvidenceStore()
                store.read(store.search(SearchRequest(tool='find_symbol', query='entry'))[0])
                check = EvidenceCheck(requested_fact='Behavior', status='supported',
                                      evidence_ids=['E1'], observed_answer='helper sonucu döndürülür.')
                ids = store.unread_claim_helpers([check])
                self.assertEqual(len(ids), 1)
                self.assertEqual(store.candidates[ids[0]].line, 3)
                self.assertEqual(len(store.blocks), 1)
                store.read(ids[0])
                self.assertEqual(store.unread_claim_helpers([check]), [])

    def test_unmentioned_or_shadowed_helper_is_not_forced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'app.py').write_text(
                'def entry(helper):\n    return helper()\ndef helper():\n    return 17\n')
            with patch.object(tools, 'PROJECT_ROOT', root):
                store = EvidenceStore()
                store.read(store.search(SearchRequest(tool='find_symbol', query='entry'))[0])
                for answer in ('entry tanımlıdır.', 'helper çağrılır.'):
                    check = EvidenceCheck(requested_fact='Behavior', status='supported',
                                          evidence_ids=['E1'], observed_answer=answer)
                    self.assertEqual(store.unread_claim_helpers([check]), [])

    def test_sibling_module_call_offers_file_and_definition_without_reading_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'pkg').mkdir()
            (root / 'pkg' / 'logic.py').write_text('def display():\n    return service.answer()\n')
            (root / 'pkg' / 'service.py').write_text('def answer():\n    return 17\n')
            with patch.object(tools, 'PROJECT_ROOT', root):
                store = EvidenceStore()
                store.read(store.search(SearchRequest(tool='find_symbol', query='display'))[0])
                actions = store.search_actions()
                self.assertIn({'tool': 'find_file', 'query': 'pkg/service.py'}, actions)
                self.assertIn({'tool': 'find_symbol', 'query': 'answer'}, actions)
                self.assertEqual({b['file'] for b in store.source_context()}, {'pkg/logic.py'})

    def test_outside_symlink_is_not_a_helper_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / 'repo'
            root.mkdir()
            (base / 'outside.py').write_text('def answer():\n    return 17\n')
            (root / 'service.py').symlink_to(base / 'outside.py')
            (root / 'logic.py').write_text('def display():\n    return service.answer()\n')
            with patch.object(tools, 'PROJECT_ROOT', root):
                store = EvidenceStore()
                store.read(store.search(SearchRequest(tool='find_symbol', query='display'))[0])
                self.assertNotIn({'tool': 'find_symbol', 'query': 'answer'}, store.search_actions())


if __name__ == '__main__':
    unittest.main()
