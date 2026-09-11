import unittest

from reference_checks import callable_statement_index


class CallableContextTests(unittest.TestCase):
    def test_return_and_raise_keep_their_lexical_owner(self):
        code = ('def caller():\n    def nested():\n        raise ValueError("bad")\n'
                '    return "message"\ndef helper():\n    return {"items": []}\n')
        rows = callable_statement_index([{
            'id': 'E1', 'file': 'sample.py', 'start_line': 10, 'quote': code}])
        self.assertEqual([(r['owner'], r['kind'], r['line']) for r in rows], [
            ('caller.nested', 'raise', 12), ('caller', 'return', 13),
            ('helper', 'return', 15)])
        self.assertEqual(rows[-1]['statement'], 'return {"items": []}')
        self.assertTrue(all(r['evidence_id'] == 'E1' for r in rows))

    def test_partial_source_does_not_invent_an_owner(self):
        rows = callable_statement_index([{
            'block_id': 'E2', 'file': 'sample.py', 'start_line': 20,
            'quote': 'return "message"'}])
        self.assertEqual(rows, [])

    def test_index_is_bounded_and_never_reads_other_files(self):
        rows = callable_statement_index([{
            'id': 'E1', 'file': 'nonexistent.py', 'start_line': 1,
            'quote': '\n'.join(f'def f{i}():\n    return {i}' for i in range(40))}])
        self.assertEqual(len(rows), 24)
