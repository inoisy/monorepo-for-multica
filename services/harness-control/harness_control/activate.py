"""Атомарная замена файлов цели и возврат прежнего набора.

Каждый файл: dst.tmp-<op> (O_EXCL|O_NOFOLLOW) → fsync → rename через dirfd. Перед первой заменой на диск пишется
журнал switch.json с копиями прежних файлов; по нему `restore` приводит набор к состоянию до замены после
любого обрыва, в том числе между двумя файлами.
"""
import contextlib
import hashlib
import json
import os
import stat
from pathlib import Path

from .errors import HarnessError
from .store import write_atomic


def _unsafe(reason):
    return HarnessError('unsafe_target', reason, 'оператор: цель выкладки должна быть обычным файлом в каталоге root без записи для других')


class Owner:
    """Кто должен владеть целями и их каталогами (root; в тестах — текущий пользователь)."""

    def __init__(self, uid=0, gid=0):
        self.uid, self.gid = uid, gid


def _walk_parent(root, host, owner):
    """Открывает каталог файла по компонентам без следования симлинкам; каждый — владелец owner, без записи другим."""
    root, host = Path(root), Path(host)
    rel = host.parent.relative_to(root)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if str(root) == '/':
            _check_dir(fd, '/', owner)
        for part in rel.parts:
            try:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as e:
                raise _unsafe(f'{part!r} в пути {host}: {"симлинк" if e.errno in (40, 20) else e.strerror}') from e
            os.close(fd)
            fd = nxt
            _check_dir(fd, str(host.parent), owner)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _check_dir(fd, label, owner):
    st = os.fstat(fd)
    if st.st_uid != owner.uid:
        raise _unsafe(f'каталог {label} принадлежит uid {st.st_uid}, ожидается {owner.uid}')
    if st.st_mode & 0o022:
        raise _unsafe(f'каталог {label} доступен на запись группе или всем (режим {stat.S_IMODE(st.st_mode):o})')


def check_target(paths, dst, owner):
    """Проверка одной цели до любой записи: каталог — root без записи другим, сама цель — обычный файл или её нет."""
    host = paths.host(dst)
    dirfd = _walk_parent(paths.root, host, owner)
    try:
        try:
            st = os.stat(host.name, dir_fd=dirfd, follow_symlinks=False)
        except FileNotFoundError:
            return host
        if stat.S_ISLNK(st.st_mode):
            raise _unsafe(f'{dst}: симлинк')
        if not stat.S_ISREG(st.st_mode):
            raise _unsafe(f'{dst}: не обычный файл')
        if st.st_mode & 0o022:
            raise _unsafe(f'{dst}: файл доступен на запись группе или всем')
        return host
    finally:
        os.close(dirfd)


def sha256_fd(fd):
    h = hashlib.sha256()
    while chunk := os.read(fd, 1 << 20):
        h.update(chunk)
    return h.hexdigest()


def current_sha(paths, dst):
    """sha256 файла цели без следования симлинкам; None, если файла нет или это не обычный файл."""
    host = paths.host(dst)
    try:
        fd = os.open(host, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        return sha256_fd(fd) if stat.S_ISREG(os.fstat(fd).st_mode) else None
    finally:
        os.close(fd)


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def _write_via_tmp(dirfd, name, tmp_name, data_fd_or_bytes, mode, owner, set_owner, expected_sha):
    """Пишет tmp целиком, сверяет хэш записанного с ожидаемым и только потом rename: усечённый файл не станет целью."""
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(tmp_name, flags, 0o600, dir_fd=dirfd)
    try:
        if isinstance(data_fd_or_bytes, bytes):
            _write_all(fd, data_fd_or_bytes)
        else:
            while chunk := os.read(data_fd_or_bytes, 1 << 20):
                _write_all(fd, chunk)
        os.fchmod(fd, mode)
        if set_owner:
            os.fchown(fd, owner.uid, owner.gid)
        os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        if sha256_fd(fd) != expected_sha:
            raise HarnessError('internal', f'{name}: записанное не совпало с ожидаемым хэшем (нет места на диске?)')
    except BaseException:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name, dir_fd=dirfd)
        raise
    os.close(fd)
    os.rename(tmp_name, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
    os.fsync(dirfd)


def _journal(path, data):
    write_atomic(path, json.dumps(data, indent=1, sort_keys=True))


def switch(paths, op_id, targets, op_dir, owner, hook=None):
    """Заменяет файлы целей. targets: [{dst, blob (Path), sha, mode}]. Возвращает журнал.

    hook(stage, index) — точки для тестов обрыва; в бою не задан."""
    hook = hook or (lambda *a: None)
    op_dir = Path(op_dir)
    backup_dir = op_dir / 'backup'
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    set_owner = os.geteuid() == 0
    # 1. Все цели проверены до первой записи: небезопасная цель ничего не меняет.
    hosts = [check_target(paths, t['dst'], owner) for t in targets]
    # 2. Копии прежних файлов и журнал.
    files = []
    for i, (t, host) in enumerate(zip(targets, hosts)):
        entry = {'dst': t['dst'], 'tmp': f'{host.name}.tmp-{op_id}', 'new_sha': t['sha256'], 'mode': int(t['mode'], 8) if isinstance(t['mode'], str) else t['mode'],
                 'existed': False, 'old_sha': None, 'old_mode': None, 'backup': None, 'state': 'pending'}
        dirfd = _walk_parent(paths.root, host, owner)
        try:
            try:
                fd = os.open(host.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
            except FileNotFoundError:
                fd = None
            if fd is not None:
                try:
                    st = os.fstat(fd)
                    data = b''.join(iter(lambda: os.read(fd, 1 << 20), b''))
                finally:
                    os.close(fd)
                backup = backup_dir / str(i)
                write_atomic(backup, data, 0o600)
                entry.update(existed=True, old_sha=hashlib.sha256(data).hexdigest(), old_mode=stat.S_IMODE(st.st_mode),
                             old_uid=st.st_uid, old_gid=st.st_gid, backup=str(backup))
        finally:
            os.close(dirfd)
        files.append(entry)
    journal = {'op': op_id, 'phase': 'switching', 'files': files}
    _journal(op_dir / 'switch.json', journal)
    hook('journaled', -1)
    # 3. Замена.
    for i, (t, host) in enumerate(zip(targets, hosts)):
        dirfd = _walk_parent(paths.root, host, owner)
        try:
            src = os.open(t['blob'], os.O_RDONLY | os.O_NOFOLLOW)
            try:
                _write_via_tmp(dirfd, host.name, files[i]['tmp'], src, files[i]['mode'], owner, set_owner, t['sha256'])
            finally:
                os.close(src)
        finally:
            os.close(dirfd)
        files[i]['state'] = 'replaced'
        _journal(op_dir / 'switch.json', journal)
        hook('replaced', i)
    journal['phase'] = 'switched'
    _journal(op_dir / 'switch.json', journal)
    return journal


def restore(paths, op_dir, owner):
    """Возвращает набор файлов к состоянию до switch по журналу. Идемпотентно. Число восстановленных файлов."""
    journal_path = Path(op_dir) / 'switch.json'
    if not journal_path.exists():
        return 0
    journal = json.loads(journal_path.read_text())
    set_owner = os.geteuid() == 0
    restored = 0
    for entry in journal['files']:
        host = paths.host(entry['dst'])
        dirfd = _walk_parent(paths.root, host, owner)
        try:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(entry['tmp'], dir_fd=dirfd)
            now = current_sha(paths, entry['dst'])
            if entry['existed']:
                if now != entry['old_sha']:
                    data = Path(entry['backup']).read_bytes()
                    _write_via_tmp(dirfd, host.name, entry['tmp'], data, entry['old_mode'], owner, set_owner, entry['old_sha'])
                    restored += 1
            elif now is not None:
                os.unlink(host.name, dir_fd=dirfd)
                restored += 1
            entry['state'] = 'restored'
        finally:
            os.close(dirfd)
    journal['phase'] = 'restored'
    _journal(journal_path, journal)
    return restored
