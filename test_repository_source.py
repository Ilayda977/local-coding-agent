"""No network, Git processes, or model calls: clone operations are mocked."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import tools
from repository_source import (RepositorySourceError, normalize_github_url,
                               prepare_repository, _git_environment)


class RepositorySourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_url_normalization(self):
        for value in ('https://github.com/owner/project', 'https://github.com/owner/project.git',
                      'https://github.com/owner/project/'):
            self.assertEqual(normalize_github_url(value), 'https://github.com/owner/project.git')

    def test_reject_non_github_and_non_repository_urls(self):
        for value in ('http://github.com/owner/project', 'https://github.com.evil.test/o/r',
                      'https://user:token@github.com/o/r', 'https://github.com:443/o/r',
                      'https://github.com/o/r/tree/main', 'https://github.com/o/r?x=y',
                      'https://github.com/o/r#main', 'file:///tmp/r', 'git@github.com:o/r',
                      'https://github.com/o/%2e%2e', 'https://github.com/o/..',
                      'https://github.com/o/r\n'):
            with self.subTest(value=value), self.assertRaises(RepositorySourceError):
                normalize_github_url(value)

    def test_local_directory_never_invokes_git(self):
        with patch('repository_source.subprocess.run') as run:
            result = prepare_repository(str(self.root))
        run.assert_not_called()
        self.assertEqual(result.path, self.root)
        self.assertIsNone(result.commit)

    def test_nonexistent_local_directory_rejected(self):
        with self.assertRaises(RepositorySourceError):
            prepare_repository(str(self.root / 'missing'))

    def test_clone_is_isolated_shallow_and_records_commit(self):
        work = self.root / 'download'
        work.mkdir()
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if 'clone' in command:
                (work / 'checkout').mkdir()
                return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
            return subprocess.CompletedProcess(command, 0, stdout='a' * 40 + '\n', stderr='')
        with patch('repository_source.shutil.which', return_value='/usr/bin/git'), \
             patch('repository_source.tempfile.mkdtemp', return_value=str(work)), \
             patch('repository_source.subprocess.run', side_effect=run):
            result = prepare_repository('https://github.com/owner/project')
        command, options = calls[0]
        for flag in ('--depth=1', '--single-branch', '--no-tags', '--no-recurse-submodules',
                     'http.followRedirects=false', 'protocol.allow=never'):
            self.assertIn(flag, command)
        self.assertFalse(options.get('shell', False))
        self.assertEqual(options['env']['GIT_TERMINAL_PROMPT'], '0')
        self.assertEqual(result.commit, 'a' * 40)
        self.assertEqual(result.metadata()['path'], str(work / 'checkout'))
        self.assertEqual(len(calls), 2)
        # A selected external repo must not gain access to its parent directory.
        with patch.object(tools, 'PROJECT_ROOT', result.path):
            self.assertIsNone(tools._resolve_safe_path('../outside.txt'))

    def test_ambient_git_configuration_is_not_inherited(self):
        with patch.dict(os.environ, {'GIT_DIR': '/secret', 'GIT_CONFIG_COUNT': '1',
                                     'GIT_CONFIG_KEY_0': 'filter.evil.smudge',
                                     'GIT_CONFIG_VALUE_0': 'unwanted-command'}):
            env = _git_environment()
        self.assertNotIn('GIT_DIR', env)
        self.assertNotIn('GIT_CONFIG_COUNT', env)
        self.assertNotIn('GIT_CONFIG_KEY_0', env)
        self.assertEqual(env['GIT_CONFIG_GLOBAL'], os.devnull)

    def test_clone_failure_reports_retained_directory(self):
        for error in (subprocess.TimeoutExpired('git', 1), subprocess.CalledProcessError(128, 'git')):
            work = self.root / type(error).__name__
            work.mkdir()
            with self.subTest(error=type(error).__name__), \
                 patch('repository_source.shutil.which', return_value='/usr/bin/git'), \
                 patch('repository_source.tempfile.mkdtemp', return_value=str(work)), \
                 patch('repository_source.subprocess.run', side_effect=error), \
                 self.assertRaisesRegex(RepositorySourceError, str(work)):
                prepare_repository('https://github.com/owner/project')
            self.assertTrue(work.exists())

    def test_missing_git_fails_before_creating_directory(self):
        with patch('repository_source.shutil.which', return_value=None), \
             patch('repository_source.tempfile.mkdtemp') as mkdir, \
             self.assertRaises(RepositorySourceError):
            prepare_repository('https://github.com/owner/project')
        mkdir.assert_not_called()


if __name__ == '__main__':
    unittest.main()
