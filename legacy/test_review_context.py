"""Context separation tests, not measurements of model accuracy."""
import unittest

from protocol import render_stage_message


class ReviewContextTests(unittest.TestCase):
    def test_review_presents_source_before_proposed_answer(self):
        block = {'block_id': 'E1', 'file': 'app.py', 'start_line': 1,
                 'end_line': 2, 'quote': 'def f():\n    return 17'}
        message = render_stage_message('VERIFY', {
            'question': 'What does f return?',
            'findings': [{'answer': 'PROPOSED_CONCLUSION', 'evidence': [block]}],
        }, {})
        self.assertLess(message.index('What does f return?'), message.index('return 17'))
        self.assertLess(message.index('return 17'), message.index('PROPOSED_CONCLUSION'))
        self.assertEqual(message.count('BEGIN UNTRUSTED SOURCE'), 1)

    def test_review_without_evidence_does_not_invent_source(self):
        message = render_stage_message('VERIFY', {
            'question': 'Question', 'findings': [{'answer': 'Claim'}],
        }, {})
        self.assertNotIn('BEGIN UNTRUSTED SOURCE', message)
        self.assertIn('Claim', message)
