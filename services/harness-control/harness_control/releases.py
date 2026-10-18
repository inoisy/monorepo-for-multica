"""Релизы компонента на диске: releases/<компонент>/<release>/{manifest.json, blobs/<sha256>}.

release — digest артефакта (64 hex) или `baseline` (файлы, найденные на сервере при установке harness).
Манифест хранит цели и хэши; при чтении хэши блобов пересчитываются.
"""
import json
import os
import shutil
import stat
from pathlib import Path

from . import activate, source
from .errors import HarnessError
from .store import sha256_file, write_atomic


def release_dir(paths, component, release_id):
    return paths.releases / component / release_id


def _publish(paths, component, release_id, manifest, blobs):
    """blobs: {sha: bytes}. Каталог собирается рядом и переименовывается целиком."""
    final = release_dir(paths, component, release_id)
    staging = final.with_name(f'.{release_id}.staging-{os.getpid()}')
    shutil.rmtree(staging, ignore_errors=True)
    (staging / 'blobs').mkdir(parents=True, mode=0o700)
    for sha, data in blobs.items():
        write_atomic(staging / 'blobs' / sha, data, 0o400)
    write_atomic(staging / 'manifest.json', json.dumps(manifest, indent=1, sort_keys=True), 0o600)
    shutil.rmtree(final, ignore_errors=True)
    os.rename(staging, final)
    return manifest


def stage(paths, policy, digest, data, work_dir):
    """Распаковывает проверенный tar и раскладывает блобы целей. Права берутся из политики, не из tar.

    Релиз назван по digest, то есть неизменяем: уже разложенный и целый каталог не пересоздаётся."""
    try:
        existing = load(paths, policy.name, digest)
        return {k: v for k, v in existing.items()}
    except HarnessError:
        pass
    tree = source.extract(data, Path(work_dir) / 'release-src')
    targets, blobs = [], {}
    try:
        for t in policy.targets:
            src = tree / t['src']
            if src.is_symlink() or not src.is_file():
                raise HarnessError('validation_failed', f'в артефакте нет файла {t["src"]}')
            content = src.read_bytes()
            sha = source.digest_of(content)
            blobs[sha] = content
            targets.append({'dst': t['dst'], 'sha256': sha, 'mode': t['mode']})
        manifest = {'component': policy.name, 'release': digest, 'source': 'git', 'targets': targets}
        return _publish(paths, policy.name, digest, manifest, blobs)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def adopt_installed(paths, policy, owner):
    """Baseline: текущие установленные файлы целей. Цель должна существовать и быть безопасной."""
    targets, blobs = [], {}
    for t in policy.targets:
        host = activate.check_target(paths, t['dst'], owner)
        if not host.is_file():
            raise HarnessError('not_installed', f'{t["dst"]} не установлен — baseline записать нельзя',
                               'оператор: установить компонент вручную и повторить install.sh')
        st = host.lstat()
        content = host.read_bytes()
        sha = source.digest_of(content)
        blobs[sha] = content
        targets.append({'dst': t['dst'], 'sha256': sha, 'mode': f'{stat.S_IMODE(st.st_mode):04o}'})
    manifest = {'component': policy.name, 'release': 'baseline', 'source': 'installed', 'targets': targets}
    return _publish(paths, policy.name, 'baseline', manifest, blobs)


def load(paths, component, release_id):
    """Манифест с путями блобов; повреждённый блоб → artifact_tampered."""
    base = release_dir(paths, component, release_id)
    try:
        manifest = json.loads((base / 'manifest.json').read_text())
    except (OSError, ValueError) as e:
        raise HarnessError('release_not_found', f'релиз {release_id[:12]} компонента {component} не найден на диске') from e
    for t in manifest['targets']:
        blob = base / 'blobs' / t['sha256']
        if not blob.is_file() or sha256_file(blob) != t['sha256']:
            raise HarnessError('artifact_tampered', f'блоб {t["sha256"][:12]} релиза {release_id[:12]} повреждён или удалён')
        t['blob'] = blob
    return manifest
