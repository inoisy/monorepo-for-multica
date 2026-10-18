"""Состояние harness-control: операции, релизы компонентов, журнал, аудит. SQLite WAL, каталог root 0700."""
import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from .errors import HarnessError

SCHEMA = '''
CREATE TABLE IF NOT EXISTS ops (
  id TEXT PRIMARY KEY, verb TEXT NOT NULL, component TEXT NOT NULL, idem_key TEXT NOT NULL,
  status TEXT NOT NULL, request TEXT NOT NULL, result TEXT, error TEXT, reason TEXT, actor TEXT,
  created_at REAL NOT NULL, updated_at REAL NOT NULL,
  UNIQUE (verb, component, idem_key)
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, op_id TEXT NOT NULL, ts REAL NOT NULL, status TEXT NOT NULL, note TEXT
);
CREATE INDEX IF NOT EXISTS events_op ON events (op_id, seq);
CREATE INDEX IF NOT EXISTS ops_component ON ops (component, created_at);
CREATE TABLE IF NOT EXISTS components (
  component TEXT PRIMARY KEY, current_release TEXT, degraded INTEGER NOT NULL DEFAULT 0,
  tests_baseline INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS releases (
  component TEXT NOT NULL, release_id TEXT NOT NULL, digest TEXT, commit_sha TEXT, source TEXT NOT NULL,
  capabilities TEXT, tests INTEGER, validation_op TEXT, deploy_op TEXT, deployed_at REAL, deployed_by TEXT,
  healthy INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
  PRIMARY KEY (component, release_id)
);
'''


def new_op_id():
    return f'{int(time.time() * 1000):013d}-{secrets.token_hex(4)}'


def _json(value):
    return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(text):
    return None if text is None else json.loads(text)


RETRYABLE = {'failed', 'interrupted'}


class Store:
    def __init__(self, paths):
        self.paths = paths
        for d in (paths.state, paths.ops, paths.artifacts, paths.releases, paths.work, paths.locks):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._local = threading.local()
        self.db.executescript(SCHEMA)
        os.chmod(paths.db, 0o600)

    @property
    def db(self):
        """Соединение на поток: общее соединение SQLite между потоками небезопасно."""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(self.paths.db, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=30000')
            self._local.conn = conn
        return conn

    # ---- операции -------------------------------------------------------------------------
    def create_op(self, verb, component, key, request, reason, actor):
        """Новая операция или уже существующая с тем же ключом: (op, created). Другой запрос под тем же ключом — отказ."""
        now = time.time()
        op_id = new_op_id()
        try:
            self.db.execute('INSERT INTO ops (id, verb, component, idem_key, status, request, reason, actor, created_at, updated_at)'
                            ' VALUES (?,?,?,?,?,?,?,?,?,?)',
                            (op_id, verb, component, key, 'queued', _json(request), reason, _json(actor), now, now))
        except sqlite3.IntegrityError:
            row = self.db.execute('SELECT * FROM ops WHERE verb=? AND component=? AND idem_key=?', (verb, component, key)).fetchone()
            existing = self._op(row)
            if existing['request'] != json.loads(_json(request)):
                raise HarnessError('idempotency_conflict', f'ключ {key!r} уже использован для другого запроса ({existing["id"]})')
            if existing['status'] not in RETRYABLE:
                return existing, False
            # Неудавшаяся или прерванная попытка не мешает повторить запрос: ключ освобождается, история остаётся.
            self.db.execute('UPDATE ops SET idem_key = idem_key || ? WHERE id=?', (f'#{existing["id"]}', existing['id']))
            return self.create_op(verb, component, key, request, reason, actor)
        self.event(op_id, 'queued', reason)
        return self.get_op(op_id), True

    def _op(self, row):
        if row is None:
            return None
        d = dict(row)
        for k in ('request', 'result', 'error', 'actor'):
            d[k] = _load(d[k])
        return d

    def get_op(self, op_id):
        op = self._op(self.db.execute('SELECT * FROM ops WHERE id=?', (op_id,)).fetchone())
        if op is None:
            raise HarnessError('operation_not_found', f'операция {op_id} не найдена')
        return op

    def ops(self, component=None, limit=50):
        sql, args = 'SELECT * FROM ops', []
        if component:
            sql += ' WHERE component=?'
            args.append(component)
        rows = self.db.execute(sql + ' ORDER BY created_at DESC, id DESC LIMIT ?', (*args, limit)).fetchall()
        return [self._op(r) for r in rows]

    def last_op(self, component):
        rows = self.ops(component, 1)
        return rows[0] if rows else None

    def set_status(self, op_id, status, note=None, result=None, error=None):
        now = time.time()
        sets, args = ['status=?', 'updated_at=?'], [status, now]
        if result is not None:
            sets.append('result=?')
            args.append(_json(result))
        if error is not None:
            sets.append('error=?')
            args.append(_json(error))
        self.db.execute(f'UPDATE ops SET {", ".join(sets)} WHERE id=?', (*args, op_id))
        self.event(op_id, status, note)

    def event(self, op_id, status, note=None):
        self.db.execute('INSERT INTO events (op_id, ts, status, note) VALUES (?,?,?,?)', (op_id, time.time(), status, note))

    def events(self, op_id):
        return [dict(r) for r in self.db.execute('SELECT ts, status, note FROM events WHERE op_id=? ORDER BY seq', (op_id,))]

    def find_op(self, verb, component, key):
        return self._op(self.db.execute('SELECT * FROM ops WHERE verb=? AND component=? AND idem_key=?', (verb, component, key)).fetchone())

    def count_unfinished(self, verb):
        return self.db.execute("SELECT COUNT(*) FROM ops WHERE verb=? AND status IN ('queued','running')", (verb,)).fetchone()[0]

    def unfinished(self):
        return [self._op(r) for r in self.db.execute(
            "SELECT * FROM ops WHERE status NOT IN ('validated','failed','done','rolled_back','degraded','interrupted') ORDER BY created_at")]

    # ---- компоненты и релизы --------------------------------------------------------------
    def component(self, name):
        row = self.db.execute('SELECT * FROM components WHERE component=?', (name,)).fetchone()
        return dict(row) if row else None

    def ensure_component(self, name, tests_baseline=0):
        self.db.execute('INSERT OR IGNORE INTO components (component, tests_baseline, updated_at) VALUES (?,?,?)',
                        (name, tests_baseline, time.time()))

    def update_component(self, name, **fields):
        fields['updated_at'] = time.time()
        sets = ', '.join(f'{k}=?' for k in fields)
        self.db.execute(f'UPDATE components SET {sets} WHERE component=?', (*fields.values(), name))

    def raise_tests_baseline(self, name, count):
        self.db.execute('UPDATE components SET tests_baseline = MAX(tests_baseline, ?), updated_at=? WHERE component=?',
                        (count, time.time(), name))

    def add_release(self, component, release_id, **fields):
        """Новая запись релиза. Уже существующая сохраняет healthy и сведения о выкладке: повторный deploy их не обнуляет."""
        fields.setdefault('source', 'git')
        fields['capabilities'] = _json(fields.get('capabilities'))
        cols = ['component', 'release_id', 'created_at', *fields]
        keep = {'healthy', 'deployed_at', 'deployed_by', 'deploy_op', 'created_at', 'component', 'release_id'}
        update = ', '.join(f'{c}=excluded.{c}' for c in cols if c not in keep)
        self.db.execute(f'INSERT INTO releases ({", ".join(cols)}) VALUES ({", ".join("?" * len(cols))})'
                        f' ON CONFLICT (component, release_id) DO UPDATE SET {update}',
                        (component, release_id, time.time(), *fields.values()))

    def release(self, component, release_id):
        row = self.db.execute('SELECT * FROM releases WHERE component=? AND release_id=?', (component, release_id)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d['capabilities'] = _load(d['capabilities'])
        return d

    def mark_release(self, component, release_id, **fields):
        sets = ', '.join(f'{k}=?' for k in fields)
        self.db.execute(f'UPDATE releases SET {sets} WHERE component=? AND release_id=?', (*fields.values(), component, release_id))

    def previous_healthy(self, component, exclude):
        row = self.db.execute('SELECT release_id FROM releases WHERE component=? AND healthy=1 AND release_id != ?'
                              ' ORDER BY COALESCE(deployed_at, created_at) DESC LIMIT 1', (component, exclude)).fetchone()
        return row['release_id'] if row else None

    def validated_op(self, op_id, component):
        """Операция validate, на которую ссылается deploy."""
        try:
            op = self.get_op(op_id)
        except HarnessError:
            raise HarnessError('validation_not_found', f'validate {op_id} не найдена') from None
        if op['verb'] != 'validate' or op['component'] != component:
            raise HarnessError('validation_not_found', f'{op_id} — не validate компонента {component}')
        return op


@contextlib.contextmanager
def file_lock(path, blocking=True, timeout=None, poll=0.2):
    """flock на файле. Возвращает True/False для неблокирующего режима и таймаута."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    got = False
    try:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking and timeout is None else fcntl.LOCK_NB))
                got = True
                break
            except BlockingIOError:
                if not blocking and timeout is None:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                time.sleep(poll)
        yield got
    finally:
        if got:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(path, data, mode=0o600):
    """Запись через temp + fsync + rename."""
    path = Path(path)
    tmp = path.with_name(f'.{path.name}.tmp-{os.getpid()}')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


class Audit:
    """audit.jsonl + syslog (journald). Атрибуция внутри uid agents декларативная: из env_keep sudoers."""

    def __init__(self, paths, logger=None):
        self.path, self.logger = paths.audit, logger

    def write(self, **entry):
        entry = {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **entry}
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (line + '\n').encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        if self.logger:
            self.logger(line)
