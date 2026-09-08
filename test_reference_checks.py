import unittest

from reference_checks import reference_index, reference_issues
from task_contract import AnswerItem


def claim(text, ids=('E1',)):
    return AnswerItem(requirement_id='Q1', answer=text, mechanism='Okunan uygulama işlemi.',
                      anchors=[{'evidence_id': key} for key in ids])


class ReferenceChecksTests(unittest.TestCase):
    def setUp(self):
        self.source = [{'id': 'E1', 'file': 'sample.py', 'quote': (
            'def clean(value):\n'
            '    # remote.fetch() is only a comment\n'
            '    label = "remote.fetch()"\n'
            '    return value.strip()\n')},
            {'id': 'E2', 'file': 'other.py', 'quote': 'def load():\n    return remote.fetch()\n'}]

    def test_comment_and_string_are_not_references(self):
        self.assertNotIn('remote.fetch', reference_index(self.source)['E1']['references'])

    def test_reference_in_other_block_does_not_support_claim(self):
        self.assertTrue(reference_issues([claim('remote.fetch çağrılır.')], self.source))

    def test_actual_cited_reference_is_accepted(self):
        self.assertEqual(reference_issues([claim('value.strip çağrılır.')], self.source), [])
        self.assertEqual(reference_issues([claim('remote.fetch çağrılır.', ('E2',))], self.source), [])

    def test_negative_absence_is_not_guessed_from_partial_source(self):
        self.assertTrue(reference_issues([claim('remote.fetch kullanılmaz.')], self.source))

    def test_unparseable_fragment_is_not_silently_accepted(self):
        source = [{'id': 'E1', 'file': 'sample.py', 'quote': 'if ready:\n'}]
        self.assertTrue(reference_issues([claim('remote.fetch çağrılır.')], source))

    def test_file_name_is_not_mistaken_for_api(self):
        self.assertEqual(reference_issues([claim('sample.py dosyasında tanımlı.')], self.source), [])

    def test_attribute_prefixes_are_recorded(self):
        source = [{'id': 'E1', 'file': 'sample.py', 'quote': 'client.session.send()'}]
        self.assertEqual(reference_index(source)['E1']['references'], ['client.session', 'client.session.send'])


if __name__ == '__main__':
    unittest.main()
