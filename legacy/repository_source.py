"""Prepare a local directory or an isolated public GitHub checkout.

Only the user-facing CLI invokes this module. The LLM cannot clone repositories
or execute shell commands. Downloaded code, hooks and dependencies are not run.
"""
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit


class RepositorySourceError(ValueError):
    pass


@dataclass(frozen=True)
class RepositorySource:
    path: Path
    url: str | None = None
    commit: str | None = None

    def metadata(self):
        return dict(asdict(self), path=str(self.path))


def normalize_github_url(value):
    """Accept only an HTTPS repository root, with optional .git/trailing slash."""
    try:
        parsed = urlsplit(value)
        valid_host = (parsed.hostname == 'github.com' and parsed.port is None
                      and parsed.username is None and parsed.password is None)
    except ValueError as error:
        raise RepositorySourceError('Geçersiz GitHub bağlantısı.') from error
    if (parsed.scheme != 'https' or not valid_host or parsed.query or parsed.fragment
            or any(char.isspace() for char in value)):
        raise RepositorySourceError('Yalnız https://github.com/SAHIP/REPO bağlantısı desteklenir.')
    parts = parsed.path.rstrip('/').split('/')
    if len(parts) != 3 or parts[0] != '':
        raise RepositorySourceError('Dosya, issue veya tree bağlantısı değil repository ana bağlantısını ver.')
    owner, repo = parts[1:]
    if repo.endswith('.git'):
        repo = repo[:-4]
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', owner)
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', repo)
            or repo in {'.', '..'} or repo.startswith('-')):
        raise RepositorySourceError('GitHub sahibi veya repository adı geçersiz.')
    return f'https://github.com/{owner}/{repo}.git'


def _git_environment():
    # Avoid ambient git config, credentials, smudge filters and repository vars.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='/usr/bin/false',
               GIT_LFS_SKIP_SMUDGE='1')
    return env


def prepare_repository(value, timeout=180):
    value = str(value).strip()
    if not value:
        raise RepositorySourceError('Repository yolu boş olamaz.')
    if '://' not in value and not value.startswith('git@'):
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            raise RepositorySourceError('--repo var olan bir klasör veya GitHub HTTPS bağlantısı olmalıdır.')
        return RepositorySource(path)
    url = normalize_github_url(value)
    git = shutil.which('git')
    if not git:
        raise RepositorySourceError('Git kurulu değil; bağlantıdan repository indirmek için git gerekli.')
    # Always a new checkout outside the coding-agent repo. Never overwrite, pull,
    # reset, delete or reuse the user's existing working tree.
    work = Path(tempfile.mkdtemp(prefix='local-coding-agent-repo-')).resolve()
    checkout = work / 'checkout'
    empty = work / 'empty-git-template'
    empty.mkdir()
    command = [git, '-c', f'core.hooksPath={empty}', '-c', 'core.fsmonitor=false',
               '-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always',
               '-c', 'http.followRedirects=false', '-c', 'credential.helper=']
    env = _git_environment()
    try:
        subprocess.run(command + ['clone', '--depth=1', '--single-branch', '--no-tags',
                                   '--no-recurse-submodules', f'--template={empty}',
                                   '--', url, str(checkout)],
                       cwd=work, env=env, check=True, capture_output=True, text=True, timeout=timeout)
        head = subprocess.run(command + ['-C', str(checkout), 'rev-parse', '--verify', 'HEAD'],
                              cwd=work, env=env, check=True, capture_output=True, text=True, timeout=15)
        commit = head.stdout.strip()
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
            raise RepositorySourceError('İndirilen repository commit kimliği doğrulanamadı.')
    except subprocess.TimeoutExpired as error:
        raise RepositorySourceError(f'Git indirme/kimlik kontrolü zaman aşımına uğradı. Kısmi dosyalar: {work}') from error
    except (subprocess.CalledProcessError, OSError) as error:
        raise RepositorySourceError(
            f'Repository indirilemedi. Bağlantıyı, ağı ve public erişimi kontrol et. '
            f'Özel repository kimlik doğrulaması desteklenmiyor. Kısmi dosyalar: {work}') from error
    return RepositorySource(checkout, url, commit)
