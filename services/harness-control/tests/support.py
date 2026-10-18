"""Окружение тестов: корень под HARNESS_ROOT, настоящие SQLite и git-репо, подменённые systemctl и systemd-run.

Проверки кандидата выполняются настоящими процессами (python3 -I -m unittest …) через подмену systemd-run, которая
разбирает те же свойства -p и подставляет /work и /checks. Root, сеть и реальные LLM-запуски не используются.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))  # python3 -I не добавляет каталог пакета сам

from harness_control.activate import Owner
from harness_control.core import Harness
from harness_control.paths import Paths
from harness_control.system import System

CANARY_DIR = 'services/harness-control/canary'
ACTOR = {'sudo_user': 'agents', 'agent': 'Бэкенд', 'task': 'TASK-264'}


class SimulatedCrash(BaseException):
    """Обрыв процесса: не перехватывается обработчиками ошибок runner'а, как и настоящее падение."""


def git(cwd, *args):
    r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
                            'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})
    assert r.returncode == 0, f'git {args}: {r.stderr}'
    return r.stdout.strip()


class OriginRepo:
    """Временный репозиторий с каталогом canary; commit() принимает файлы относительно каталога canary (None — удалить)."""

    def __init__(self, directory):
        self.path = Path(directory)
        self.path.mkdir(parents=True)
        git(self.path, 'init', '-q', '-b', 'main')
        self.files = {}
        for f in (PKG / 'canary').rglob('*'):
            if f.is_file() and '__pycache__' not in f.parts:
                self.files[str(f.relative_to(PKG / 'canary'))] = f.read_text()
        self.commit({}, 'init')

    def commit(self, changes, message='c', branch=None):
        if branch:
            git(self.path, 'switch', '-q', '-C', branch)
        for rel, content in changes.items():
            target = self.path / CANARY_DIR / rel
            if content is None:
                self.files.pop(rel, None)
                target.unlink(missing_ok=True)
            else:
                self.files[rel] = content
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                if rel.endswith('.py') and rel == 'canary.py':
                    target.chmod(0o755)
        if not (self.path / CANARY_DIR).exists():
            (self.path / CANARY_DIR).mkdir(parents=True)
        for rel, content in self.files.items():
            target = self.path / CANARY_DIR / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        git(self.path, 'add', '-A')
        git(self.path, 'commit', '-q', '--allow-empty', '-m', message)
        sha = git(self.path, 'rev-parse', 'HEAD')
        if branch:
            git(self.path, 'switch', '-q', 'main')
        return sha


class FakeSystem(System):
    """systemctl с состоянием юнитов и таймеров + песочница systemd-run, выполняющая команды локально."""

    def __init__(self, paths):
        super().__init__(paths, bare=True)
        self.now = time.time()
        self.units = {}
        self.calls = []
        self.active_timers = {}
        self.timer_service = {}
        self.sandbox_calls = []
        self.sandbox_override = None
        self.tick_effects = {}
        self.fail_calls = set()
        self.lock = threading.Lock()

    def add_service(self, name, timer=None, interval=60):
        self.units[name] = {'ActiveState': 'inactive', 'Result': 'success', 'ExecMainStartTimestamp': None, 'ExecMainStatus': '0'}
        if timer:
            self.units[timer] = {'ActiveState': 'inactive', 'UnitFileState': 'enabled'}
            self.timer_service[timer] = (name, interval)

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.advance(seconds)

    def advance(self, seconds):
        with self.lock:
            self.now += seconds
            for timer, next_fire in list(self.active_timers.items()):
                if self.now >= next_fire:
                    service, interval = self.timer_service[timer]
                    self.active_timers[timer] = self.now + interval
                    self._fire(service)

    def _fire(self, service):
        effect = self.tick_effects.get(service)
        result = effect(self) if effect else 'success'
        self.units[service].update(ExecMainStartTimestamp=int(self.now), ActiveState='inactive', Result=result,
                                   ExecMainStatus='0' if result == 'success' else '1')

    def calls_of(self, verb):
        return [u for v, u in self.calls if v == verb]

    # ---- перехват запуска программ ----------------------------------------------------------
    def run(self, argv, timeout=60, env=None, input=None, cwd=None, binary=False):
        name = os.path.basename(argv[0])
        if name == 'systemctl':
            return self._systemctl(argv[1:])
        if name == 'systemd-run':
            return self._sandbox(argv)
        return super().run(argv, timeout=timeout, env=env, input=input, cwd=cwd, binary=binary)

    def _done(self, out='', rc=0, err=''):
        return subprocess.CompletedProcess([], rc, out, err)

    def _systemctl(self, args):
        verb = args[0]
        if verb == 'show':
            unit = args[1]
            if '--value' in args:
                return self._done('loaded\n' if unit in self.units else 'not-found\n')
            props = self.units.get(unit, {'ActiveState': 'inactive'})
            lines = []
            for a in args[2:]:
                if a.startswith('-p'):
                    key = a[2:]
                    value = props.get(key)
                    if key.endswith('Timestamp') or key.endswith('USec'):
                        value = f'@{value}' if value else ''
                    lines.append(f'{key}={"" if value is None else value}')
            return self._done('\n'.join(lines) + '\n')
        rest = [a for a in args[1:] if a != '--now']
        unit = rest[-1]
        if (verb, unit) in self.fail_calls:
            return self._done(rc=1, err=f'Failed to {verb} {unit}')
        with self.lock:
            self.calls.append((verb, unit))
            if verb in ('start', 'enable') and unit in self.timer_service:
                self.units[unit]['ActiveState'] = 'active'
                self.active_timers[unit] = self.now + self.timer_service[unit][1]
            elif verb in ('stop', 'disable') and unit in self.timer_service:
                self.units[unit]['ActiveState'] = 'inactive'
                self.active_timers.pop(unit, None)
        return self._done()

    def _sandbox(self, argv):
        props, setenv, cmd, binds = [], {}, [], {}
        i = 1
        while i < len(argv):
            a = argv[i]
            if a == '--':
                cmd = argv[i + 1:]
                break
            if a == '-p':
                props.append(argv[i + 1])
                i += 2
                continue
            if a.startswith('--setenv='):
                k, _, v = a[len('--setenv='):].partition('=')
                setenv[k] = v
            i += 1
        for p in props:
            if p.startswith('BindReadOnlyPaths='):
                src, _, dst = p[len('BindReadOnlyPaths='):].partition(':')
                binds[dst] = src
        self.sandbox_calls.append({'argv': argv, 'props': props, 'env': setenv, 'cmd': cmd})
        if self.sandbox_override:
            override = self.sandbox_override(cmd)
            if override is not None:
                return override
        def remap(s):
            for dst, src in binds.items():
                if s == dst or s.startswith(dst + '/'):
                    return src + s[len(dst):]
            return s
        local = [remap(c) for c in cmd]
        r = subprocess.run(local, cwd=binds.get('/work'), env=setenv, capture_output=True, text=True, timeout=300)
        tail = 'Finished with result: success' if r.returncode == 0 else \
            f'Finished with result: exit-code\nMain processes terminated with: code=exited, status={r.returncode}/FAILURE'
        return subprocess.CompletedProcess(argv, r.returncode, r.stdout, (r.stderr + '\n' + tail).strip())


def canary_effect(root, name='harness-canary'):
    """Плановый запуск canary: пишет status.json со временем тика; версия с «fail» даёт сбой."""
    def effect(system):
        version = (root / f'usr/local/lib/{name}/VERSION').read_text().strip()
        failed = 'fail' in version
        state = root / f'var/lib/{name}'
        state.mkdir(parents=True, exist_ok=True)
        tick = dt.datetime.fromtimestamp(system.now, dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        (state / 'status.json').write_text(json.dumps({'tick': tick, 'version': version, 'errors': ['сбой'] if failed else []}))
        return 'exit-code' if failed else 'success'
    return effect


class HarnessCase(unittest.TestCase):
    """Корень, политика canary из пакета (источник — временный репо), baseline, подмены."""
    component = 'harness-canary'
    max_parallel = 1
    policy_patch = None
    install = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='hc-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'root'
        self.paths = Paths(self.root)
        self.origin = OriginRepo(self.tmp / 'origin')
        self.pending = []
        self.write_etc()
        self.build_lib()
        self.system = FakeSystem(self.paths)
        self.system.add_service('harness-canary.service', 'harness-canary.timer')
        self.system.tick_effects['harness-canary.service'] = canary_effect(self.root)
        self.install_canary_files()
        self.h = self.make_harness()
        self.system.advance(1)
        if self.install:
            self.h.adopt_baseline('harness-canary')

    def make_harness(self, **kw):
        return Harness(self.paths, system=self.system, spawn=self.pending.append, owner=Owner(os.getuid(), os.getgid()),
                       clock=self.system.clock, sleep=self.system.sleep, http=kw.pop('http', lambda url: 302), **kw)

    def policy(self):
        raw = json.loads((PKG / 'policy.d' / 'harness-canary.json').read_text())
        raw['source']['repo'] = str(self.origin.path)
        raw['health']['poll'] = 5
        if self.policy_patch:
            self.policy_patch(raw)
        return raw

    def write_etc(self, raw=None):
        etc = self.paths.policy_dir
        etc.mkdir(parents=True, exist_ok=True)
        (etc / 'harness-canary.json').write_text(json.dumps(raw or self.policy(), indent=1))
        (self.paths.etc / 'harness.json').write_text(json.dumps({'agent_user': 'agents', 'max_parallel_validate': self.max_parallel,
                                                                  'lock_timeout': 30}))

    def build_lib(self):
        self.paths.lib.mkdir(parents=True, exist_ok=True)
        (self.paths.lib / 'VERSION').write_text('test-1\n')
        shutil.copytree(PKG / 'checks', self.paths.checks, dirs_exist_ok=True)

    def install_canary_files(self):
        d = self.root / 'usr/local/lib/harness-canary'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'canary.py').write_text((PKG / 'canary/canary.py').read_text())
        (d / 'canary.py').chmod(0o755)
        (d / 'VERSION').write_text('0\n')
        os.chmod(d, 0o755)

    def dst(self, name):
        return self.root / 'usr/local/lib/harness-canary' / name

    def drain(self):
        """Выполняет поставленные в очередь операции так, как это сделал бы runner."""
        results = []
        while self.pending:
            results.append(self.h.run_operation(self.pending.pop(0)))
        return results

    def validated(self, changes=None, key=None, branch=None):
        sha = self.origin.commit(changes or {'VERSION': '5\n'}, 'v', branch=branch)
        r = self.h.validate('harness-canary', sha, key, 'test', ACTOR)
        self.drain()
        op = self.h.op(r['operation_id'])
        return sha, op

    def deploy_args(self, op):
        return {'component': self.component, 'validation': op['operation_id'], 'digest': op['result']['digest']}

    def deploy(self, op, key=None):
        r = self.h.deploy(**self.deploy_args(op), key=key, reason='test', actor=ACTOR)
        self.drain()
        return self.h.op(r['operation_id'])


def add_component(case, name):
    """Второй независимый компонент той же формы, что canary (свои файлы, юниты, статус, политика)."""
    raw = json.loads((case.paths.policy_dir / 'harness-canary.json').read_text())
    text = json.dumps(raw).replace('harness-canary', name)
    (case.paths.policy_dir / f'{name}.json').write_text(text)
    shutil.copytree(case.paths.checks / 'harness-canary', case.paths.checks / name)
    d = case.root / f'usr/local/lib/{name}'
    d.mkdir(parents=True)
    (d / 'canary.py').write_text((PKG / 'canary/canary.py').read_text())
    (d / 'canary.py').chmod(0o755)
    (d / 'VERSION').write_text('0\n')
    case.system.add_service(f'{name}.service', f'{name}.timer')
    case.system.tick_effects[f'{name}.service'] = canary_effect(case.root, name)
    case.h.adopt_baseline(name)
