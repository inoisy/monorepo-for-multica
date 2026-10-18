"""Источник кандидата: зеркало публичного репо, канонический tar, безопасная распаковка.

Digest артефакта — sha256 tar, который выдал `git archive <sha>:<путь>`. Root берёт код из репо по sha,
без ключей агента; происхождение — коммит.
"""
import hashlib
import io
import os
import re
import shutil
import tarfile
from pathlib import Path

from .errors import HarnessError
from .store import write_atomic
from .system import MAX_OUTPUT

SHA = re.compile(r'^[0-9a-f]{40}$')
MAX_FILES = 5000


class Source:
    def __init__(self, paths, system):
        self.paths, self.system = paths, system

    def _repo_dir(self, policy):
        return self.paths.mirror / policy.name

    def _protocol(self, policy):
        return 'https' if policy.source['repo'].startswith('https://') else 'file'

    def sync(self, policy, sha):
        """Обновляет зеркало и убеждается, что коммит в нём есть."""
        git_dir = self._repo_dir(policy)
        proto = self._protocol(policy)
        if not git_dir.is_dir():
            git_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            r = self.system.run([self.system.exe('git'), 'init', '--bare', '-q', str(git_dir)], env=self._env(proto))
            if r.returncode:
                raise HarnessError('internal', f'git init: {r.stderr.strip()[:200]}')
        repo = policy.source['repo']
        r = self.system.git(git_dir, 'fetch', '--prune', '--no-tags', '-q', repo, '+refs/heads/*:refs/remotes/origin/*', protocol=proto)
        if r.returncode:
            raise HarnessError('internal', f'git fetch {repo}: {r.stderr.strip()[:300]}')
        if self.system.git(git_dir, 'cat-file', '-e', f'{sha}^{{commit}}', protocol=proto).returncode:
            r = self.system.git(git_dir, 'fetch', '--no-tags', '-q', repo, sha, protocol=proto)
            if r.returncode or self.system.git(git_dir, 'cat-file', '-e', f'{sha}^{{commit}}', protocol=proto).returncode:
                raise HarnessError('validation_failed', f'коммит {sha} не найден в {repo}')

    def _env(self, proto):
        from .system import GIT_ENV
        return {**GIT_ENV, 'GIT_ALLOW_PROTOCOL': proto}

    def reachable(self, policy, sha):
        """Достижим ли коммит из require_ref (None — проверка отключена оператором)."""
        ref = policy.source['require_ref']
        if ref is None:
            return True
        git_dir = self._repo_dir(policy)
        if not git_dir.is_dir():
            return False
        r = self.system.git(git_dir, 'merge-base', '--is-ancestor', sha, f'refs/remotes/{ref}', protocol=self._protocol(policy))
        return r.returncode == 0

    def archive(self, policy, sha):
        r = self.system.git(self._repo_dir(policy), 'archive', '--format=tar', f'{sha}:{policy.source["path"]}',
                            protocol=self._protocol(policy), binary=True)
        if r.returncode:
            raise HarnessError('validation_failed', f'git archive {sha}:{policy.source["path"]}: {r.stderr.decode(errors="replace").strip()[:300]}')
        if len(r.stdout) >= MAX_OUTPUT:
            raise HarnessError('validation_failed', f'артефакт больше {MAX_OUTPUT >> 20} МБ')
        return r.stdout

    def commit_info(self, policy, sha):
        r = self.system.git(self._repo_dir(policy), 'show', '-s', '--format=%cI%n%an%n%s', sha, protocol=self._protocol(policy))
        parts = (r.stdout.splitlines() + ['', '', ''])[:3] if r.returncode == 0 else ['', '', '']
        return {'committed_at': parts[0], 'author': parts[1], 'subject': parts[2][:200]}


def digest_of(data):
    return hashlib.sha256(data).hexdigest()


def store_artifact(paths, data):
    """Неизменяемый tar: имя — digest, права 0400. Возвращает digest."""
    digest = digest_of(data)
    target = paths.artifacts / f'{digest}.tar'
    if not target.exists():
        write_atomic(target, data, 0o400)
    return digest


def artifact_path(paths, digest):
    return paths.artifacts / f'{digest}.tar'


def verified_artifact(paths, digest):
    """Читает tar и пересчитывает хэш; подмена или потеря → artifact_tampered."""
    path = artifact_path(paths, digest)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise HarnessError('artifact_tampered', f'артефакт {digest[:12]} недоступен: {e.strerror}') from e
    if digest_of(data) != digest:
        raise HarnessError('artifact_tampered', f'артефакт {digest[:12]} изменён после validate: хэш {digest_of(data)[:12]}')
    return data


def extract(data, dest):
    """Распаковка без симлинков, устройств и выхода за каталог. Права: 0755 каталогам, 0644/0755 файлам."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, mode=0o755)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as tar:
        for member in tar:
            count += 1
            if count > MAX_FILES:
                raise HarnessError('validation_failed', f'в артефакте больше {MAX_FILES} файлов')
            name = member.name
            if name.startswith('/') or '..' in Path(name).parts:
                raise HarnessError('validation_failed', f'недопустимый путь в артефакте: {name!r}')
            target = dest / name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o755)
                os.chmod(target, 0o755)
            elif member.isreg():
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with tar.extractfile(member) as src, open(target, 'wb') as out:
                    shutil.copyfileobj(src, out)
                os.chmod(target, 0o755 if member.mode & 0o111 else 0o644)
            else:
                raise HarnessError('validation_failed', f'в артефакте нельзя {name!r}: только файлы и каталоги')
    return dest
