"""Planning regressions; no Ollama, shell execution or patch application."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools
from evidence import EvidenceStore
from patch_protocol import ChangePlan, propose_change
from protocol import SearchRequest


def proposal(ids=None):
    return {'status': 'proposed', 'reason': 'Small change', 'changes': [{
        'evidence_ids': ids or ['E1'], 'change': 'Clarify the message.',
        'expected_result': 'A clearer message.', 'risk': 'Callers may compare strings.',
        'validation': 'Check a message assertion.'}]}


class PlanningTests(unittest.TestCase):
    def test_unknown_evidence_is_rejected(self):
        plan = ChangePlan.model_validate(proposal(['invented']))
        with self.assertRaises(ValueError):
            plan.validate_context({'source': [{'id': 'E1', 'file': 'app.py'}]})

    def test_multiple_files_are_rejected(self):
        plan = ChangePlan.model_validate(proposal(['E1', 'E2']))
        with self.assertRaises(ValueError):
            plan.validate_context({'source': [
                {'id': 'E1', 'file': 'a.py'}, {'id': 'E2', 'file': 'b.py'}]})

    def test_no_change_is_valid_but_cannot_include_a_change(self):
        ChangePlan.model_validate({'status': 'no_change', 'reason': 'Already correct.', 'changes': []})
        value = proposal()
        value['status'] = 'no_change'
        with self.assertRaises(ValueError):
            ChangePlan.model_validate(value)

    def test_proposal_resolves_file_from_evidence_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'app.py'
            source.write_text('def message():\n    return "hello"\n')
            before = source.read_bytes()
            with patch.object(tools, 'PROJECT_ROOT', root):
                store = EvidenceStore()
                store.read(store.search(SearchRequest(tool='find_symbol', query='message'))[0])
                class Gateway:
                    def ask(self, stage, model, instruction, data):
                        return model.model_validate(proposal())
                result = propose_change('Improve the message.', [], store, Gateway())
                self.assertEqual(result['changes'][0]['file'], 'app.py')
                self.assertFalse(result['applied'])
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(list(root.iterdir()), [source])
