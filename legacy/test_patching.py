"""No model, network, shell or repository code execution in patch safety tests."""
from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from patching import PatchError, prepare_patch, get_diff, apply_patch, rollback


class SafePatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name) / 'repo'
        self.repo.mkdir()
        self.path = self.repo / 'calc.py'
        self.original = '# small fixture\ndef add(a, b):\n    return a - b\n'
        self.path.write_text(self.original, encoding='utf-8')

    def preview(self):
        return prepare_patch(self.repo, 'calc.py', 'return a - b', 'return a + b')

    def test_preview_is_read_only_and_immutable(self):
        preview = self.preview()
        self.assertEqual(self.path.read_text(), self.original)
        self.assertIn('-    return a - b', get_diff(preview))
        self.assertIn('+    return a + b', get_diff(preview))
        with self.assertRaises(FrozenInstanceError):
            preview.diff = 'changed'

    def test_three_easy_patches_apply_and_rollback(self):
        examples = [
            ('def add(a, b):\n    return a - b\n', 'a - b', 'a + b'),
            ('def full(n, limit):\n    return n > limit\n', 'n > limit', 'n >= limit'),
            ('def enabled(value):\n    return not value\n', 'not value', 'bool(value)'),
        ]
        for code, old, new in examples:
            with self.subTest(code=code):
                self.path.write_text(code)
                preview = prepare_patch(self.repo, 'calc.py', old, new)
                receipt = apply_patch(preview, preview.approval_id)
                self.assertEqual(self.path.read_text(), code.replace(old, new))
                self.assertTrue(rollback(receipt, receipt.rollback_id))
                self.assertEqual(self.path.read_text(), code)

    def test_missing_wrong_or_model_boolean_approval_cannot_write(self):
        preview = self.preview()
        for token in (None, '', True, 'yes', 'APPLY-invented'):
            with self.subTest(token=token), self.assertRaises(PatchError):
                apply_patch(preview, token)
        self.assertEqual(self.path.read_text(), self.original)

    def test_changed_patch_requires_new_approval(self):
        first = self.preview()
        second = prepare_patch(self.repo, 'calc.py', 'a - b', 'a * b')
        self.assertNotEqual(first.approval_id, second.approval_id)
        with self.assertRaises(PatchError):
            apply_patch(second, first.approval_id)

    def test_different_target_requires_new_approval(self):
        (self.repo / 'other.py').write_text(self.original)
        second = prepare_patch(self.repo, 'other.py', 'return a - b', 'return a + b')
        self.assertNotEqual(self.preview().approval_id, second.approval_id)

    def test_tampered_preview_rejected(self):
        for preview in (replace(self.preview(), diff='fake diff'),
                        replace(self.preview(), replacement=b'other content')):
            with self.assertRaises(PatchError):
                apply_patch(preview, preview.approval_id)
        self.assertEqual(self.path.read_text(), self.original)

    def test_stale_file_not_overwritten(self):
        preview = self.preview()
        self.path.write_text(self.original + '# user edit\n')
        with self.assertRaises(PatchError):
            apply_patch(preview, preview.approval_id)
        self.assertIn('# user edit', self.path.read_text())

    def test_evidence_hash_is_checked_before_preview(self):
        digest = hashlib.sha256(self.original.encode()).hexdigest()
        prepare_patch(self.repo, 'calc.py', 'a - b', 'a + b', expected_hash=digest)
        with self.assertRaises(PatchError):
            prepare_patch(self.repo, 'calc.py', 'a - b', 'a + b', expected_hash='stale')

    def test_rollback_refuses_intervening_user_edit(self):
        preview = self.preview()
        receipt = apply_patch(preview, preview.approval_id)
        self.path.write_text(self.path.read_text() + '# user edit\n')
        with self.assertRaises(PatchError):
            rollback(receipt, receipt.rollback_id)
        self.assertIn('# user edit', self.path.read_text())

    def test_rollback_requires_distinct_approval(self):
        preview = self.preview()
        receipt = apply_patch(preview, preview.approval_id)
        with self.assertRaises(PatchError):
            rollback(receipt, preview.approval_id)

    def test_noop_empty_old_missing_and_ambiguous_blocks_rejected(self):
        for old, new in [('a - b', 'a - b'), ('', 'x'), ('missing', 'x'), ('a', 'x')]:
            with self.subTest(old=old), self.assertRaises(PatchError):
                prepare_patch(self.repo, 'calc.py', old, new)

    def test_whole_file_rewrite_rejected(self):
        with self.assertRaises(PatchError):
            prepare_patch(self.repo, 'calc.py', self.original, 'print(1)\n')

    def test_invalid_python_rejected_without_execution(self):
        with self.assertRaises(PatchError):
            prepare_patch(self.repo, 'calc.py', 'return a - b', 'return (')
        self.assertEqual(self.path.read_text(), self.original)

    def test_outside_and_metadata_secret_paths_rejected(self):
        for name in ('../outside.py', str(self.path), 'nested/../calc.py', '.git/config',
                     '.env', '.env.local', 'secrets/config.txt', 'credentials.json', 'id_rsa',
                     'key.pem', 'folder\\calc.py', 'calc.py\n', 'calc.py:stream'):
            with self.subTest(name=name), self.assertRaises(PatchError):
                prepare_patch(self.repo, name, 'a', 'b')

    def test_no_new_files(self):
        with self.assertRaises(PatchError):
            prepare_patch(self.repo, 'missing.py', 'a', 'b')

    def test_final_symlink_rejected_even_inside_repo(self):
        (self.repo / 'alias.py').symlink_to(self.path)
        with self.assertRaises(PatchError):
            prepare_patch(self.repo, 'alias.py', 'a - b', 'a + b')

    def test_directory_symlink_rejected(self):
        (self.repo / 'alias').symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(PatchError):
            prepare_patch(self.repo, 'alias/calc.py', 'a - b', 'a + b')

    def test_file_replaced_by_outside_symlink_after_preview_rejected(self):
        preview = self.preview()
        outside = Path(self.directory.name) / 'outside.py'
        outside.write_text(self.original)
        self.path.unlink()
        self.path.symlink_to(outside)
        with self.assertRaises(PatchError):
            apply_patch(preview, preview.approval_id)
        self.assertEqual(outside.read_text(), self.original)

    def test_hardlinks_rejected(self):
        (self.repo / 'alias.py').hardlink_to(self.path)
        with self.assertRaises(PatchError):
            self.preview()

    def test_permission_preserved_and_external_permission_change_rejected(self):
        self.path.chmod(0o750)
        preview = self.preview()
        receipt = apply_patch(preview, preview.approval_id)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o750)
        rollback(receipt, receipt.rollback_id)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o750)
        self.path.chmod(0o640)
        with self.assertRaises(PatchError):
            apply_patch(preview, preview.approval_id)

    def test_atomic_replace_failure_keeps_original_and_removes_temp(self):
        preview = self.preview()
        with patch('patching.os.replace', side_effect=OSError('injected failure')):
            with self.assertRaises(PatchError):
                apply_patch(preview, preview.approval_id)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(list(self.repo.glob('.local-agent-patch-*')), [])

    def test_binary_and_non_utf8_rejected(self):
        for content in (b'hello\0world', b'\xff\xfe'):
            self.path.write_bytes(content)
            with self.assertRaises(PatchError):
                self.preview()

    def test_file_and_changed_line_limits(self):
        self.path.write_text('a' * (128 * 1024 + 1))
        with self.assertRaises(PatchError):
            self.preview()
        old = ''.join(f'old{i}\n' for i in range(40))
        new = ''.join(f'new{i}\n' for i in range(40))
        (self.repo / 'text.txt').write_text('header\n' + old + 'footer\n')
        with self.assertRaises(PatchError):
            prepare_patch(self.repo, 'text.txt', old, new)

    def test_utf8_turkish_and_missing_final_newline(self):
        path = self.repo / 'açıklama.txt'
        path.write_text('başlık\nişlem yanlış', encoding='utf-8')
        preview = prepare_patch(self.repo, path.name, 'işlem yanlış', 'işlem doğru')
        self.assertIn('No newline at end of file', preview.diff)
        apply_patch(preview, preview.approval_id)
        self.assertEqual(path.read_text(), 'başlık\nişlem doğru')

    def test_crlf_preserved(self):
        self.path.write_bytes(self.original.replace('\n', '\r\n').encode())
        preview = self.preview()
        apply_patch(preview, preview.approval_id)
        self.assertEqual(self.path.read_bytes(), self.original.replace('a - b', 'a + b').replace('\n', '\r\n').encode())


if __name__ == '__main__':
    unittest.main()
