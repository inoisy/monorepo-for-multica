"""Политика компонентов. Читается только из /etc/harness-control/policy.d (root), кандидат на неё не влияет.

policy_version = sha256(политика + каталог checks компонента + версия harness): любое изменение
инвалидирует старые validate.
"""
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .errors import HarnessError

COMPONENT = re.compile(r'[a-z0-9][a-z0-9-]{0,39}')
FORBIDDEN = {
    'multica-agents': 'daemon платформы: рестарт убивает активные раны, вне первого этапа',
    'multica-daemon': 'daemon платформы: рестарт убивает активные раны, вне первого этапа',
    'multica': 'платформа Multica не управляется через harness-control',
    'multica-platform': 'платформа Multica не управляется через harness-control',
    'multica-backend': 'backend платформы не управляется через harness-control',
    'multica-web': 'web платформы не управляется через harness-control',
    'harness-control': 'самообновление harness-control вне первого этапа',
}
MODE = re.compile(r'0[0-7]{3}')
UNIT = re.compile(r'[A-Za-z0-9:_.@-]+\.(service|timer)')
SIZE = re.compile(r'[0-9]+[KMG]?')

SANDBOX_DEFAULTS = {'memory_max': '2G', 'tasks_max': 256, 'runtime_max_sec': 1800,
                    'path': '/usr/local/bin:/usr/bin:/bin'}
HEALTH_DEFAULTS = {'timeout': 600, 'poll': 5, 'units': [], 'status_files': [], 'http': [], 'commands': []}


class PolicyError(ValueError):
    pass


def _expect(cond, message):
    if not cond:
        raise PolicyError(message)


def _only_keys(obj, allowed, where):
    _expect(isinstance(obj, dict), f'{where}: нужен объект')
    extra = set(obj) - set(allowed)
    _expect(not extra, f'{where}: неизвестные ключи {sorted(extra)}')


def _strings(value, where, pattern=None):
    _expect(isinstance(value, list) and all(isinstance(x, str) for x in value), f'{where}: нужен список строк')
    if pattern:
        for x in value:
            _expect(pattern.fullmatch(x), f'{where}: недопустимое значение {x!r}')
    return value


def hash_tree(directory):
    """Хэш каталога checks: путь, признак исполняемости, содержимое. Симлинки запрещены."""
    h = hashlib.sha256()
    directory = Path(directory)
    if not directory.is_dir():
        return hashlib.sha256(b'').hexdigest()
    for path in sorted(directory.rglob('*')):
        st = path.lstat()
        _expect(not stat.S_ISLNK(st.st_mode), f'checks: симлинк {path}')
        if stat.S_ISREG(st.st_mode):
            h.update(f'{path.relative_to(directory)}\0{st.st_mode & 0o111 != 0}\0'.encode())
            h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


class Policy:
    """Проверенная политика одного компонента."""

    def __init__(self, raw, raw_bytes, checks_hash, harness_version):
        self.raw = self._validate(raw)
        self.name = raw['component']
        self.raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        canonical = json.dumps({'policy': self.raw_sha, 'checks': checks_hash, 'harness': harness_version},
                               sort_keys=True)
        self.version = hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _validate(raw):
        _only_keys(raw, {'component', 'description', 'source', 'targets', 'timers', 'busy_units', 'restart_units',
                         'required_units', 'lanes', 'baseline_capabilities', 'capabilities', 'validate', 'sandbox',
                         'health', 'dependencies'}, 'policy')
        _expect(isinstance(raw.get('component'), str) and COMPONENT.fullmatch(raw['component']), 'component: [a-z0-9-]{1,40}')
        _expect(raw['component'] not in FORBIDDEN, 'component: запрещённое имя')
        source = raw.get('source')
        _only_keys(source, {'repo', 'path', 'require_ref'}, 'source')
        _expect(isinstance(source.get('repo'), str) and re.fullmatch(r'https://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._/-]+|/[A-Za-z0-9._/-]+', source['repo']), 'source.repo: https://хост/путь без учётных данных или абсолютный путь')
        _expect(isinstance(source.get('path'), str) and re.fullmatch(r'^[A-Za-z0-9._/-]+$', source['path'])
                and '..' not in source['path'].split('/') and not source['path'].startswith('/'), 'source.path')
        ref = source.get('require_ref', 'origin/main')
        _expect(ref is None or (isinstance(ref, str) and re.fullmatch(r'^origin/[A-Za-z0-9._/-]+$', ref)), 'source.require_ref')
        raw['source'] = {'repo': source['repo'], 'path': source['path'], 'require_ref': ref}
        targets = raw.get('targets')
        _expect(isinstance(targets, list) and targets, 'targets: непустой список')
        seen = set()
        for i, t in enumerate(targets):
            _only_keys(t, {'src', 'dst', 'mode'}, f'targets[{i}]')
            _expect(isinstance(t.get('src'), str) and re.fullmatch(r'^[A-Za-z0-9._-][A-Za-z0-9._/-]*$', t['src'])
                    and '..' not in t['src'].split('/'), f'targets[{i}].src')
            _expect(isinstance(t.get('dst'), str) and re.fullmatch(r'^/[A-Za-z0-9._/-]+$', t['dst'])
                    and '..' not in t['dst'].split('/') and '//' not in t['dst'] and not t['dst'].endswith('/'), f'targets[{i}].dst')
            _expect(isinstance(t.get('mode'), str) and MODE.fullmatch(t['mode']), f'targets[{i}].mode: 0644 / 0755')
            _expect(t['dst'] not in seen, f'targets[{i}]: дублируется {t["dst"]}')
            seen.add(t['dst'])
        for key in ('timers', 'busy_units', 'required_units'):
            raw[key] = _strings(raw.get(key, []), key, UNIT)
        restarts = []
        for i, r in enumerate(raw.get('restart_units', [])):
            _only_keys(r, {'unit', 'when_changed'}, f'restart_units[{i}]')
            _expect(isinstance(r.get('unit'), str) and UNIT.fullmatch(r['unit']), f'restart_units[{i}].unit')
            changed = _strings(r.get('when_changed', []), f'restart_units[{i}].when_changed')
            _expect(all(c in seen for c in changed), f'restart_units[{i}].when_changed: не из targets')
            restarts.append({'unit': r['unit'], 'when_changed': changed})
        raw['restart_units'] = restarts
        lanes = raw.get('lanes', {})
        _expect(isinstance(lanes, dict), 'lanes')
        for lane, spec in lanes.items():
            _expect(re.fullmatch(r'^[a-z][a-z0-9-]*$', lane), f'lanes.{lane}')
            _only_keys(spec, {'timers'}, f'lanes.{lane}')
            _strings(spec.get('timers', []), f'lanes.{lane}.timers', UNIT)
        raw['lanes'] = {lane: {'timers': list(spec.get('timers', []))} for lane, spec in lanes.items()}
        base = raw.get('baseline_capabilities', {'lanes': []})
        _only_keys(base, {'lanes'}, 'baseline_capabilities')
        _strings(base.get('lanes', []), 'baseline_capabilities.lanes')
        raw['baseline_capabilities'] = {'lanes': list(base.get('lanes', []))}
        caps = raw.get('capabilities')
        if caps is not None:
            _only_keys(caps, {'argv'}, 'capabilities')
            _strings(caps.get('argv'), 'capabilities.argv')
        raw['capabilities'] = caps
        val = raw.get('validate', {})
        _only_keys(val, {'checks', 'tests'}, 'validate')
        checks = val.get('checks', [])
        _expect(isinstance(checks, list), 'validate.checks')
        for i, c in enumerate(checks):
            _only_keys(c, {'name', 'argv'}, f'validate.checks[{i}]')
            _expect(isinstance(c.get('name'), str) and re.fullmatch(r'^[a-z0-9_-]{1,40}$', c['name']), f'validate.checks[{i}].name')
            _strings(c.get('argv'), f'validate.checks[{i}].argv')
        tests = val.get('tests')
        if tests is not None:
            _only_keys(tests, {'argv', 'count_regex', 'min'}, 'validate.tests')
            _strings(tests.get('argv'), 'validate.tests.argv')
            re.compile(tests.get('count_regex', ''))
            _expect(isinstance(tests.get('min', 0), int) and tests.get('min', 0) >= 0, 'validate.tests.min')
            tests = {'argv': tests['argv'], 'count_regex': tests.get('count_regex', r'Ran (\d+) tests?'), 'min': tests.get('min', 0)}
        raw['validate'] = {'checks': checks, 'tests': tests}
        sb = {**SANDBOX_DEFAULTS, **raw.get('sandbox', {})}
        _only_keys(raw.get('sandbox', {}), set(SANDBOX_DEFAULTS), 'sandbox')
        _expect(isinstance(sb['memory_max'], str) and SIZE.fullmatch(sb['memory_max']), 'sandbox.memory_max')
        _expect(isinstance(sb['tasks_max'], int) and 1 <= sb['tasks_max'] <= 100000, 'sandbox.tasks_max')
        _expect(isinstance(sb['runtime_max_sec'], int) and 1 <= sb['runtime_max_sec'] <= 86400, 'sandbox.runtime_max_sec')
        _expect(isinstance(sb['path'], str) and re.fullmatch(r'^[A-Za-z0-9._:/-]+$', sb['path']), 'sandbox.path')
        raw['sandbox'] = sb
        health = {**HEALTH_DEFAULTS, **raw.get('health', {})}
        _only_keys(raw.get('health', {}), set(HEALTH_DEFAULTS), 'health')
        _expect(isinstance(health['timeout'], int) and 1 <= health['timeout'] <= 3600, 'health.timeout')
        _expect(isinstance(health['poll'], (int, float)) and health['poll'] > 0, 'health.poll')
        for i, u in enumerate(health['units']):
            _only_keys(u, {'unit', 'timer', 'lane'}, f'health.units[{i}]')
            _expect(isinstance(u.get('unit'), str) and UNIT.fullmatch(u['unit']), f'health.units[{i}].unit')
            _expect(u.get('timer') is None or UNIT.fullmatch(u['timer']), f'health.units[{i}].timer')
            _expect(u.get('lane') is None or u['lane'] in raw['lanes'], f'health.units[{i}].lane')
        for i, s in enumerate(health['status_files']):
            _only_keys(s, {'path', 'tick_key', 'errors_key', 'events_key', 'bad_event_kinds', 'lane'}, f'health.status_files[{i}]')
            _expect(isinstance(s.get('path'), str) and s['path'].startswith('/'), f'health.status_files[{i}].path')
            _expect(isinstance(s.get('tick_key'), str), f'health.status_files[{i}].tick_key')
            _expect(s.get('lane') is None or s['lane'] in raw['lanes'], f'health.status_files[{i}].lane')
        for i, h in enumerate(health['http']):
            _only_keys(h, {'url', 'expect'}, f'health.http[{i}]')
            _expect(isinstance(h.get('url'), str) and re.fullmatch(r'http://127\.0\.0\.1(:\d+)?/[A-Za-z0-9._/?=&-]*', h['url']), f'health.http[{i}].url: только 127.0.0.1')
            _expect(isinstance(h.get('expect'), list) and all(isinstance(c, int) for c in h['expect']), f'health.http[{i}].expect')
        for i, c in enumerate(health['commands']):
            _only_keys(c, {'name', 'argv'}, f'health.commands[{i}]')
            _strings(c.get('argv'), f'health.commands[{i}].argv')
        raw['health'] = health
        deps = raw.get('dependencies', {})
        _only_keys(deps, {'tools', 'fresh_files', 'state_files'}, 'dependencies')
        raw['dependencies'] = {'tools': _strings(deps.get('tools', []), 'dependencies.tools'),
                               'fresh_files': deps.get('fresh_files', []), 'state_files': _strings(deps.get('state_files', []), 'dependencies.state_files')}
        for i, f in enumerate(raw['dependencies']['fresh_files']):
            _only_keys(f, {'name', 'path', 'path_from_json', 'max_age'}, f'dependencies.fresh_files[{i}]')
        raw['description'] = str(raw.get('description', ''))
        return raw

    def __getattr__(self, item):
        try:
            return self.__dict__['raw'][item]
        except KeyError:
            raise AttributeError(item) from None


class Policies:
    def __init__(self, paths, harness_version):
        self.paths, self.harness_version = paths, harness_version

    def get(self, component):
        """Политика компонента. Запрещённые имена и неизвестные отказываются раньше любой работы."""
        if not isinstance(component, str) or not COMPONENT.fullmatch(component):
            raise HarnessError('bad_request', f'component: ожидается [a-z0-9-]{{1,40}}, получено {str(component)[:60]!r}')
        if component in FORBIDDEN:
            raise HarnessError('forbidden_component', f'{component}: {FORBIDDEN[component]}',
                               'оператор: компонент добавляется только отдельным решением и новой политикой')
        path = self.paths.policy_dir / f'{component}.json'
        if not path.is_file():
            raise HarnessError('unknown_component', f'{component}: нет политики в {self.paths.policy_dir}',
                               'оператор: добавить policy.d/<компонент>.json и переустановить пакет')
        return self._load(path)

    def names(self):
        d = self.paths.policy_dir
        return sorted(p.stem for p in d.glob('*.json')) if d.is_dir() else []

    def _load(self, path):
        raw_bytes = path.read_bytes()
        try:
            raw = json.loads(raw_bytes)
            policy = Policy(raw, raw_bytes, hash_tree(self.paths.checks / path.stem), self.harness_version)
        except (PolicyError, ValueError, re.error) as e:
            raise HarnessError('internal', f'политика {path.name} некорректна: {e}', 'оператор: исправить политику') from e
        if policy.name != path.stem:
            raise HarnessError('internal', f'политика {path.name}: component не совпадает с именем файла')
        return policy

    def check_secure(self):
        """Политику и sudoers держит root: файл политики не должен быть доступен на запись другим."""
        problems = []
        d = self.paths.policy_dir
        if d.is_dir():
            for p in [d, *d.glob('*.json')]:
                st = p.stat()
                if st.st_mode & 0o022:
                    problems.append(f'{p}: доступен на запись не владельцу')
        return problems
