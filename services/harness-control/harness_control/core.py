"""Владелец поведения harness-control: допуск, операции, состояние. CLI и MCP — тонкие адаптеры над `Harness.handle`.

Исполняется только root-входом harness-priv и runner'ом операции.
"""
import contextlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import activate, releases, safefile, sandbox, source
from .activate import Owner
from .errors import HarnessError
from .health import Health, http_status
from .policy import Policies
from .redact import redact
from .store import Audit, Store, file_lock, write_atomic
from .system import System

SHA = re.compile(r'^[0-9a-f]{40}$')
DIGEST = re.compile(r'^sha256:([0-9a-f]{64})$')
KEY = re.compile(r'^[A-Za-z0-9._:-]{1,80}$')
OP_ID = re.compile(r'^[0-9]{13}-[0-9a-f]{8}$')
RELEASE = re.compile(r'^(baseline|[0-9a-f]{64})$')
ACTOR_FIELD = re.compile(r'[^A-Za-z0-9._:@ -]')
REASON_MAX = 500
LOG_MAX = 4 << 20
MAX_QUEUED_VALIDATE = 8
SERVICE_PATH = '/usr/local/bin:/usr/bin:/bin'  # PATH служб обвязки: по нему ищутся инструменты зависимостей

AGENT_VERBS = {'inspect', 'validate', 'deploy', 'rollback', 'op', 'log', 'ops'}
ADMIN_VERBS = {'adopt-baseline', 'recover', 'run-op'}
DEFAULT_CONFIG = {'agent_user': 'agents', 'max_parallel_validate': 1, 'lock_timeout': 3600}


def load_config(paths):
    config = dict(DEFAULT_CONFIG)
    path = paths.etc / 'harness.json'
    if path.is_file():
        config.update(json.loads(path.read_text()))
    return config


def clean_actor(env):
    """Кто просит: SUDO_USER + MULTICA_*. Атрибуция внутри uid agents декларативная."""
    pick = lambda name: ACTOR_FIELD.sub('', env.get(name, ''))[:80]
    return {'sudo_user': pick('SUDO_USER'), 'agent': pick('MULTICA_AGENT_NAME'), 'task': pick('MULTICA_TASK_ID')}


def actor_label(actor):
    return '/'.join(x for x in (actor.get('sudo_user'), actor.get('agent'), actor.get('task')) if x) or 'unknown'


def clean_reason(reason):
    reason = '' if reason is None else str(reason)
    reason = ''.join(ch for ch in reason if ch >= ' ' or ch in '\n\t')
    if len(reason) > REASON_MAX:
        raise HarnessError('bad_request', f'reason: не больше {REASON_MAX} символов (получено {len(reason)})')
    return reason


def iso(ts):
    return None if not ts else time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))


class Harness:
    def __init__(self, paths, system=None, spawn=None, owner=None, clock=time.time, sleep=time.sleep, http=http_status,
                 audit_logger=None, hooks=None):
        self.paths = paths
        self.system = system or System(paths)
        self.owner = owner or Owner()
        self.config = load_config(paths)
        self.version = (paths.lib / 'VERSION').read_text().strip() if (paths.lib / 'VERSION').is_file() else '0'
        self.policies = Policies(paths, self.version)
        self.store = Store(paths)
        self.audit = Audit(paths, audit_logger)
        self.source = source.Source(paths, self.system)
        self.clock, self.sleep = clock, sleep
        self.hooks = hooks or {}
        self.spawn = spawn or (lambda op_id: self.system.spawn_runner(op_id, str(paths.lib / 'bin' / 'runner')))
        self.health = Health(paths, self.system, self._sandbox_check, clock=clock, sleep=sleep, http=http)

    def _hook(self, name, *args):
        if name in self.hooks:
            self.hooks[name](*args)

    # ===================================================================================
    # Диспетчер: единая точка для harness-priv, тестов и паритета адаптеров
    # ===================================================================================
    def handle(self, verb, args, actor=None):
        """Выполняет verb и возвращает JSON-совместимый dict; отказ — {error, reason, missing}."""
        actor = actor or {'sudo_user': '', 'agent': '', 'task': ''}
        try:
            self._authorize(verb, actor)
            result = self._dispatch(verb, args, actor)
        except HarnessError as e:
            self._audit(verb, args, actor, outcome=e.code, reason=e.reason)
            return e.to_dict()
        if verb in {'validate', 'deploy', 'rollback', 'adopt-baseline'}:
            self._audit(verb, args, actor, outcome='accepted', operation=result.get('operation_id'), status=result.get('status'))
        return result

    def _authorize(self, verb, actor):
        if verb in ADMIN_VERBS:
            if actor.get('sudo_user') == self.config['agent_user']:
                raise HarnessError('verb_not_allowed', f'{verb}: действие оператора, не агента',
                                   'оператор (root): выполнить через sudo harness-priv от своего пользователя')
        elif verb not in AGENT_VERBS:
            raise HarnessError('verb_not_allowed', f'неизвестное действие {str(verb)[:40]!r}')

    def _audit(self, verb, args, actor, **fields):
        entry = {'verb': verb, 'actor': actor, 'component': args.get('component'), 'key': args.get('key'),
                 'reason': args.get('reason'), 'digest': args.get('digest'), **fields}
        self.audit.write(**{k: v for k, v in entry.items() if v is not None})

    def _dispatch(self, verb, a, actor):
        if verb == 'inspect':
            return self.inspect(a.get('component'))
        if verb == 'validate':
            return self.validate(a['component'], a['sha'], a.get('key'), a.get('reason'), actor)
        if verb == 'deploy':
            return self.deploy(a['component'], a['validation'], a['digest'], a.get('key'), a.get('reason'), actor)
        if verb == 'rollback':
            return self.rollback(a['component'], a.get('to'), a.get('reason'), actor)
        if verb == 'op':
            return self.op(a['id'])
        if verb == 'log':
            return self.log(a['id'], a.get('tail'))
        if verb == 'ops':
            return self.ops(a.get('component'))
        if verb == 'adopt-baseline':
            return self.adopt_baseline(a['component'])
        if verb == 'recover':
            return self.recover()
        if verb == 'run-op':
            return self.run_operation(a['id'])
        raise HarnessError('verb_not_allowed', f'неизвестное действие {verb!r}')

    # ===================================================================================
    # Допуск
    # ===================================================================================
    def _require_installed(self, policy):
        """Юниты из пакета оператора на месте и baseline записан — иначе выкладывать не из чего."""
        missing = [u for u in self._all_units(policy, required_only=True) if not self.system.unit_exists(u)]
        if missing:
            raise HarnessError('not_installed', f'{policy.name}: нет юнитов systemd {", ".join(missing)}',
                               'оператор (root): установить юниты пакетом install.sh')
        if self.store.release(policy.name, 'baseline') is None:
            raise HarnessError('not_installed', f'{policy.name}: baseline не записан',
                               'оператор (root): sudo /usr/local/lib/harness-control/install.sh --adopt ' + policy.name)

    def _all_units(self, policy, required_only=False):
        units = list(policy.required_units)
        if not required_only:
            units += policy.timers + policy.busy_units + [r['unit'] for r in policy.restart_units]
            units += [u['unit'] for u in policy.health['units']] + [t for l in policy.lanes.values() for t in l['timers']]
        seen = []
        for u in units:
            if u not in seen:
                seen.append(u)
        return seen

    def _check_validation(self, policy, validation_id, digest_arg):
        """Допуск deploy: validate есть и успешна, digest и политика те же, артефакт цел."""
        m = DIGEST.fullmatch(digest_arg or '')
        if not m:
            raise HarnessError('bad_request', 'digest: ожидается sha256:<64 hex>')
        if not OP_ID.fullmatch(validation_id or ''):
            raise HarnessError('bad_request', 'validation: ожидается идентификатор операции')
        val = self.store.validated_op(validation_id, policy.name)
        if val['status'] != 'validated':
            raise HarnessError('validation_failed', f'validate {validation_id} имеет статус {val["status"]}',
                               'запустить validate заново и дождаться validated')
        result = val['result']
        if result['digest'] != digest_arg:
            raise HarnessError('digest_mismatch', f'digest в запросе {digest_arg[:19]}… не равен проверенному {result["digest"][:19]}…')
        if result['policy_version'] != policy.version:
            raise HarnessError('policy_changed', f'политика компонента изменилась после validate {validation_id}',
                               'повторить validate под новой политикой')
        source.verified_artifact(self.paths, m.group(1))
        return val

    def _check_deployable(self, policy, val):
        comp = self.store.component(policy.name)
        if comp and comp['degraded']:
            raise HarnessError('locked_degraded', f'{policy.name} заблокирован после неудачного отката',
                               'выполнить rollback и убедиться, что health прошёл')
        if policy.source['require_ref'] is not None:
            sha = val['request']['sha']
            if not (val['result'].get('reachable') and self.source.reachable(policy, sha)):
                raise HarnessError('ref_not_allowed', f'коммит {sha[:12]} недостижим из {policy.source["require_ref"]}',
                                   'влить коммит в основную ветку или оператору ослабить require_ref в политике')

    # ===================================================================================
    # Публичные глаголы
    # ===================================================================================
    def _submit(self, verb, policy, key, request, reason, actor):
        op, created = self.store.create_op(verb, policy.name, key, request, clean_reason(reason), actor)
        if created:
            try:
                self.spawn(op['id'])
            except HarnessError as e:
                self.store.set_status(op['id'], 'failed', e.reason, error=e.to_dict())
                raise
        return {'operation_id': op['id'], 'status': op['status'], 'created': created}

    def validate(self, component, sha, key=None, reason=None, actor=None):
        policy = self.policies.get(component)
        if not SHA.fullmatch(sha or ''):
            raise HarnessError('bad_request', 'sha: ожидается полный sha1 коммита, 40 hex')
        if key is not None and not KEY.fullmatch(key):
            raise HarnessError('bad_request', 'key: [A-Za-z0-9._:-]{1,80}')
        self.store.ensure_component(policy.name, policy.validate['tests']['min'] if policy.validate['tests'] else 0)
        if (self.store.find_op('validate', policy.name, key or sha) is None
                and self.store.count_unfinished('validate') >= MAX_QUEUED_VALIDATE):
            raise HarnessError('busy', f'в очереди уже {MAX_QUEUED_VALIDATE} проверок', 'повторить позже, когда часть завершится')
        return self._submit('validate', policy, key or sha, {'sha': sha}, reason, actor or {})

    def deploy(self, component, validation, digest, key=None, reason=None, actor=None):
        policy = self.policies.get(component)
        if key is not None and not KEY.fullmatch(key):
            raise HarnessError('bad_request', 'key: [A-Za-z0-9._:-]{1,80}')
        val = self._check_validation(policy, validation, digest)
        self._require_installed(policy)
        self._check_deployable(policy, val)
        return self._submit('deploy', policy, key or f'{validation}:{digest}', {'validation': validation, 'digest': digest}, reason, actor or {})

    def rollback(self, component, to=None, reason=None, actor=None):
        policy = self.policies.get(component)
        if to is not None and not RELEASE.fullmatch(to):
            raise HarnessError('bad_request', 'to: baseline или digest релиза (64 hex)')
        self._require_installed(policy)
        target = self._rollback_target(policy, to)
        releases.load(self.paths, policy.name, target)
        return self._submit('rollback', policy, f'{target}:{time.time_ns()}', {'to': target}, reason, actor or {})

    def _rollback_target(self, policy, to):
        comp = self.store.component(policy.name)
        if to:
            release = self.store.release(policy.name, to)
            if release is None:
                raise HarnessError('release_not_found', f'релиз {to[:12]} компонента {policy.name} неизвестен')
            if not release['healthy']:
                raise HarnessError('release_not_found', f'релиз {to[:12]} не проходил health: откатываться на него нельзя')
            return to
        current = comp['current_release'] if comp else None
        if comp and comp['degraded'] and current:
            return current
        target = self.store.previous_healthy(policy.name, current or '')
        if not target:
            raise HarnessError('release_not_found', f'{policy.name}: нет проверенного релиза, на который можно откатиться')
        return target

    def op(self, op_id):
        if not OP_ID.fullmatch(op_id or ''):
            raise HarnessError('bad_request', 'id: ожидается идентификатор операции')
        op = self.store.get_op(op_id)
        return {'operation_id': op['id'], 'verb': op['verb'], 'component': op['component'], 'status': op['status'],
                'request': op['request'], 'reason': op['reason'], 'actor': op['actor'], 'result': op['result'],
                'error': op['error'], 'created_at': iso(op['created_at']), 'updated_at': iso(op['updated_at']),
                'events': [{'at': iso(e['ts']), 'status': e['status'], 'note': e['note']} for e in self.store.events(op_id)]}

    def ops(self, component=None):
        if component is not None:
            self.policies.get(component)
        return {'operations': [{'operation_id': o['id'], 'verb': o['verb'], 'component': o['component'], 'status': o['status'],
                                'created_at': iso(o['created_at']), 'error': (o['error'] or {}).get('error')} for o in self.store.ops(component)]}

    def log(self, op_id, tail=None):
        if not OP_ID.fullmatch(op_id or ''):
            raise HarnessError('bad_request', 'id: ожидается идентификатор операции')
        if tail is not None and not (isinstance(tail, int) and 1 <= tail <= 10000):
            raise HarnessError('bad_request', 'tail: от 1 до 10000 строк')
        self.store.get_op(op_id)
        path = self.paths.op_dir(op_id) / 'log.txt'
        text = path.read_text(errors='replace') if path.is_file() else ''
        lines = text.splitlines()
        shown = lines[-tail:] if tail else lines
        return {'operation_id': op_id, 'lines': len(lines), 'truncated': len(shown) < len(lines), 'log': redact('\n'.join(shown))}

    # ===================================================================================
    # Исполнение операции (runner)
    # ===================================================================================
    def run_operation(self, op_id):
        op = self.store.get_op(op_id)
        if op['status'] != 'queued':
            return {'operation_id': op_id, 'status': op['status']}
        self.paths.op_dir(op_id).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store.set_status(op_id, 'running')
        try:
            policy = self.policies.get(op['component'])
            handler = {'validate': self._run_validate, 'deploy': self._run_deploy, 'rollback': self._run_rollback}[op['verb']]
            handler(op, policy)
        except HarnessError as e:
            self._log(op_id, f'ОТКАЗ {e.code}: {e.reason}')
            self.store.set_status(op_id, 'failed', e.reason, error=e.to_dict())
        except Exception as e:  # сбой окружения: фиксируем и не теряем причину
            self._log(op_id, f'СБОЙ {type(e).__name__}: {e}')
            self.store.set_status(op_id, 'failed', str(e), error=HarnessError('internal', f'{type(e).__name__}: {e}').to_dict())
        return self.op(op_id)

    def _log(self, op_id, text, literals=()):
        path = self.paths.op_dir(op_id) / 'log.txt'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_size >= LOG_MAX:
                return
            data = (redact(text, literals).rstrip('\n') + '\n').encode()
            if os.fstat(fd).st_size + len(data) >= LOG_MAX:
                data = data[:max(0, LOG_MAX - os.fstat(fd).st_size - 64)] + '\n[лог операции достиг предела и обрезан]\n'.encode()
            os.write(fd, data)
        finally:
            os.close(fd)

    # ---- validate ------------------------------------------------------------------------
    def _run_validate(self, op, policy):
        op_id, sha = op['id'], op['request']['sha']
        self._log(op_id, f'== validate {policy.name} {sha} (политика {policy.version[:12]})')
        with file_lock(self.paths.locks / f'mirror-{policy.name}.lock', timeout=600) as got:
            if not got:
                raise HarnessError('busy', 'зеркало репозитория занято другой проверкой', 'повторить позже')
            self.source.sync(policy, sha)
        reachable = self.source.reachable(policy, sha)
        data = self.source.archive(policy, sha)
        digest = source.store_artifact(self.paths, data)
        self._log(op_id, f'артефакт sha256:{digest}, {len(data)} байт; достижим из {policy.source["require_ref"]}: {reachable}')
        work = self.paths.work / op_id
        try:
            tree = source.extract(data, work / 'src')
            os.chmod(work, 0o755)
            for t in policy.targets:
                f = tree / t['src']
                if f.is_symlink() or not f.is_file():
                    raise HarnessError('validation_failed', f'в коммите нет файла {t["src"]}', None)
            limits = policy.sandbox
            checks_dir = self.paths.checks / policy.name
            checks_dir.mkdir(parents=True, exist_ok=True)
            steps = [(c['name'], c['argv']) for c in policy.validate['checks']]
            tests = policy.validate['tests']
            if tests:
                steps.append(('tests', tests['argv']))
            ran, count = [], None
            with sandbox.slot(self.paths, self.config['max_parallel_validate'], self.config['lock_timeout']) as slot:
                if slot is None:
                    raise HarnessError('busy', 'нет свободного места для validate: идут другие проверки', 'повторить позже')
                self._hook('validate_started', op_id)
                for name, argv in steps:
                    self._log(op_id, f'-- {name}: {" ".join(argv)}')
                    outcome, output = sandbox.run(self.system, limits, tree, checks_dir, argv, limits['runtime_max_sec'])
                    self._log(op_id, output)
                    ran.append({'check': name, **{k: outcome[k] for k in ('ok', 'exit_code', 'signal', 'timeout', 'oom_kill')}})
                    self._log(op_id, f'-- {name}: ok={outcome["ok"]} exit_code={outcome["exit_code"]} signal={outcome["signal"]} '
                                     f'timeout={outcome["timeout"]} oom_kill={outcome["oom_kill"]}')
                    if name == 'tests':
                        count = self._count_tests(tests['count_regex'], output)
                        self._enforce_test_count(policy, count, outcome, op_id)
                    if not outcome['ok']:
                        primary = {'check': name, **{k: outcome[k] for k in ('exit_code', 'signal', 'timeout', 'oom_kill', 'result')}}
                        raise HarnessError('validation_failed', self._primary_text(primary), 'исправить причину и повторить validate') \
                            .with_primary(primary)
                capabilities = {'lanes': []}
                if policy.capabilities:
                    capabilities = self._probe_capabilities(policy, tree, checks_dir, op_id)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        result = {'digest': f'sha256:{digest}', 'commit': sha, 'policy_version': policy.version, 'reachable': reachable,
                  'tests': count, 'capabilities': capabilities, 'checks': ran, 'commit_info': self.source.commit_info(policy, sha)}
        if count is not None and reachable:
            # счётчик печатает сам кандидат, поэтому порог поднимают только коммиты из основной ветки
            self.store.raise_tests_baseline(policy.name, count)
        self._log(op_id, f'validated: digest sha256:{digest}, тестов {count}')
        self.store.set_status(op_id, 'validated', f'digest sha256:{digest}', result=result)

    @staticmethod
    def _primary_text(p):
        why = 'таймаут' if p['timeout'] else 'oom-kill' if p['oom_kill'] else f'сигнал {p["signal"]}' if p['signal'] else f'код выхода {p["exit_code"]}'
        return f'проверка {p["check"]} не прошла: {why}'

    @staticmethod
    def _count_tests(pattern, output):
        found = re.findall(pattern, output)
        return int(found[-1]) if found else None

    def _enforce_test_count(self, policy, count, outcome, op_id):
        comp = self.store.component(policy.name) or {}
        required = max(policy.validate['tests']['min'], comp.get('tests_baseline', 0))
        if (count or 0) < required:
            raise HarnessError('tests_decreased', f'тестов {count or 0}, а у последней проверенной версии не меньше {required}',
                               'вернуть удалённые тесты; изменить порог может только оператор') \
                .with_primary({'check': 'tests', 'exit_code': outcome['exit_code'], 'signal': outcome['signal'],
                               'timeout': outcome['timeout'], 'oom_kill': outcome['oom_kill'], 'result': outcome['result']})

    def _probe_capabilities(self, policy, tree, checks_dir, op_id):
        limits = policy.sandbox
        self._log(op_id, f'-- capabilities: {" ".join(policy.capabilities["argv"])}')
        outcome, output = sandbox.run(self.system, limits, tree, checks_dir, policy.capabilities['argv'], limits['runtime_max_sec'])
        try:
            caps = json.loads(next(l for l in reversed(output.strip().splitlines()) if l.lstrip().startswith('{')))
            assert isinstance(caps.get('lanes'), list) and all(isinstance(x, str) for x in caps['lanes'])
        except (StopIteration, ValueError, AssertionError, AttributeError):
            outcome = {**outcome, 'ok': False}
        if not outcome['ok']:
            primary = {'check': 'capabilities', 'exit_code': outcome['exit_code'], 'signal': outcome['signal'],
                       'timeout': outcome['timeout'], 'oom_kill': outcome['oom_kill'], 'result': outcome['result']}
            raise HarnessError('validation_failed', 'capabilities: нет корректного JSON {"lanes": [...]}').with_primary(primary)
        self._log(op_id, f'capabilities: {json.dumps(caps, ensure_ascii=False)}')
        return {'lanes': sorted(set(caps['lanes'])), 'raw': caps}

    # ---- deploy --------------------------------------------------------------------------
    def _component_lock(self, policy):
        return file_lock(self.paths.locks / f'component-{policy.name}.lock', blocking=True, timeout=self.config['lock_timeout'])

    def _run_deploy(self, op, policy):
        op_id, req = op['id'], op['request']
        digest = req['digest']
        self._log(op_id, f'== deploy {policy.name} {digest} (validate {req["validation"]})')
        with self._component_lock(policy) as got:
            if not got:
                raise HarnessError('busy', f'{policy.name}: другая операция держит компонент больше {self.config["lock_timeout"]} с', 'повторить позже')
            # Всё, что было проверено при приёме запроса, проверяется снова: между приёмом и запуском мог быть чужой deploy или правка политики.
            val = self._check_validation(policy, req['validation'], digest)
            self._require_installed(policy)
            self._check_deployable(policy, val)
            data = source.verified_artifact(self.paths, DIGEST.fullmatch(digest).group(1))
            comp = self.store.component(policy.name)
            old_id = comp['current_release'] or 'baseline'
            old = releases.load(self.paths, policy.name, old_id)
            if DIGEST.fullmatch(digest).group(1) == old_id and not comp['degraded'] and self._no_drift(policy, old):
                self.store.set_status(op_id, 'done', 'эта версия уже выложена, дрейфа нет', result={'release': old_id, 'noop': True})
                return
            work = self.paths.work / op_id
            work.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                new_id = DIGEST.fullmatch(digest).group(1)
                new = releases.stage(self.paths, policy, new_id, data, work)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            self.store.add_release(policy.name, new_id, digest=digest, commit_sha=val['request']['sha'], source='git',
                                   capabilities=val['result']['capabilities'], tests=val['result']['tests'], validation_op=val['id'])
            self.store.set_status(op_id, 'staged', f'релиз {new_id[:12]} разложен')
            self._hook('staged', op_id)
            new = releases.load(self.paths, policy.name, new_id)
            outcome = self._switch_and_check(op, policy, new, new_id, check_busy=True, from_id=old_id)
            if outcome['ok']:
                self._mark_current(policy, new_id, op, actor_label(op['actor'] or {}))
                self.store.set_status(op_id, 'done', 'health пройден', result={'release': new_id, 'health': outcome})
                return
            self._log(op_id, f'health не прошёл: {json.dumps(outcome, ensure_ascii=False)}')
            self.store.mark_release(policy.name, new_id, healthy=0)
            self._hook('before_auto_rollback', op_id)
            try:
                back = self._switch_and_check(op, policy, old, old_id, check_busy=False, side='back', from_id=new_id)
            except Exception:
                self.store.update_component(policy.name, degraded=1)
                raise
            if back['ok']:
                self._mark_current(policy, old_id, op, None, touch=False)
                self.store.set_status(op_id, 'rolled_back', 'health новой версии не прошёл, возвращена предыдущая',
                                      result={'release': old_id, 'failed_release': new_id, 'health': outcome, 'rollback_health': back})
            else:
                self.store.update_component(policy.name, degraded=1, current_release=old_id)
                self.store.set_status(op_id, 'degraded', 'откат тоже не прошёл health: компонент заблокирован до явного rollback',
                                      result={'release': old_id, 'failed_release': new_id, 'health': outcome, 'rollback_health': back})

    def _mark_current(self, policy, release_id, op, deployed_by, touch=True):
        fields = {'healthy': 1}
        if touch:
            fields.update(deployed_at=self.clock(), deployed_by=deployed_by, deploy_op=op['id'])
        self.store.mark_release(policy.name, release_id, **fields)
        self.store.update_component(policy.name, current_release=release_id, degraded=0)

    # ---- rollback ------------------------------------------------------------------------
    def _run_rollback(self, op, policy):
        op_id, target_id = op['id'], op['request']['to']
        self._log(op_id, f'== rollback {policy.name} → {target_id[:12]}')
        with self._component_lock(policy) as got:
            if not got:
                raise HarnessError('busy', f'{policy.name}: другая операция держит компонент', 'повторить позже')
            comp = self.store.component(policy.name)
            current_id = comp['current_release'] or 'baseline'
            target = releases.load(self.paths, policy.name, target_id)
            current = releases.load(self.paths, policy.name, current_id)
            if target_id == current_id and not comp['degraded'] and self._no_drift(policy, current):
                self.store.set_status(op_id, 'done', 'уже на этой версии', result={'release': target_id, 'noop': True})
                return
            outcome = self._switch_and_check(op, policy, target, target_id, check_busy=True, from_id=current_id)
            if outcome['ok']:
                self._mark_current(policy, target_id, op, actor_label(op['actor'] or {}))
                self.store.set_status(op_id, 'done', 'health пройден', result={'release': target_id, 'health': outcome})
            else:
                self.store.update_component(policy.name, degraded=1)
                self.store.set_status(op_id, 'degraded', 'откат не прошёл health: компонент заблокирован до следующего rollback',
                                      result={'release': target_id, 'health': outcome})

    def _no_drift(self, policy, manifest):
        return all(activate.current_sha(self.paths, t['dst']) == t['sha256'] for t in manifest['targets'])

    # ---- общая активация -----------------------------------------------------------------
    def _lane_timers(self, policy):
        return {lane: spec['timers'] for lane, spec in policy.lanes.items()}

    def lanes_of(self, policy, release_id):
        if release_id == 'baseline':
            return set(policy.baseline_capabilities['lanes'])
        release = self.store.release(policy.name, release_id)
        return set((release['capabilities'] or {}).get('lanes', [])) if release else set()

    def apply_units(self, policy, lanes, changed=None):
        """Перезапуск юнитов из политики (только если изменились их файлы) и включение таймеров по полосам релиза."""
        for r in policy.restart_units:
            if changed is None or not r['when_changed'] or any(d in changed for d in r['when_changed']):
                self.system.restart(r['unit'])
        for t in policy.timers:
            self.system.start(t)
        for lane, timers in self._lane_timers(policy).items():
            for t in timers:
                (self.system.enable_now if lane in lanes else self.system.disable_now)(t)

    def _switch_and_check(self, op, policy, new, new_id, check_busy, side='forward', from_id='baseline'):
        """Останавливает таймеры, меняет файлы, перезапускает юниты, включает полосы по capabilities, ждёт health."""
        op_id = op['id']
        lanes = self.lanes_of(policy, new_id)
        lane_timers = self._lane_timers(policy)
        all_timers = list(dict.fromkeys(policy.timers + [t for ts in lane_timers.values() for t in ts]))
        was_active = {t: self.system.unit_props(t, ['ActiveState'])['ActiveState'] == 'active' for t in all_timers}
        for t in all_timers:
            self.system.stop(t)
        try:
            self._hook(f'{side}:timers_stopped', op_id)
            if check_busy:
                for u in policy.busy_units:
                    if self.system.is_busy(u):
                        raise HarnessError('busy', f'{u} выполняется — тик не прерываем', 'повторить deploy после завершения тика')
            self.store.set_status(op_id, 'switching', f'{side}: {len(new["targets"])} файлов')
            before = {t['dst']: activate.current_sha(self.paths, t['dst']) for t in new['targets']}
            activate.switch(self.paths, f'{op_id}-{side}', new['targets'], self.paths.op_dir(op_id) / side, self.owner,
                            hook=lambda stage, i: self._hook(f'{side}:{stage}', i))
            self._hook(f'{side}:switched', op_id)
            since = self.clock()
            changed = {t['dst'] for t in new['targets'] if before.get(t['dst']) != t['sha256']}
            self.apply_units(policy, lanes, changed)
            self.store.set_status(op_id, 'health', f'{side}: ждём плановый запуск')
            outcome = self.health.wait(policy, lanes, since)
            self._hook(f'{side}:health_done', op_id)
            return outcome
        except Exception:
            self._abort_switch(op, policy, side, was_active, self.lanes_of(policy, from_id))
            raise

    def _abort_switch(self, op, policy, side, was_active, old_lanes):
        """Сбой до или во время замены: файлы возвращаются из журнала, юниты и таймеры — в прежнее состояние."""
        restored = 0
        with contextlib.suppress(Exception):
            restored = activate.restore(self.paths, self.paths.op_dir(op['id']) / side, self.owner)
        if restored:
            for r in policy.restart_units:
                with contextlib.suppress(Exception):
                    self.system.restart(r['unit'])
        lane_timers = {t for timers in self._lane_timers(policy).values() for t in timers}
        for t, active in was_active.items():
            with contextlib.suppress(Exception):
                if active:
                    self.system.start(t)
                elif t in lane_timers:
                    self.system.disable_now(t)
                else:
                    self.system.stop(t)

    # ===================================================================================
    # Baseline и восстановление (действия оператора / загрузки)
    # ===================================================================================
    def adopt_baseline(self, component):
        policy = self.policies.get(component)
        if self.store.release(policy.name, 'baseline'):
            return {'component': component, 'baseline': 'exists'}
        manifest = releases.adopt_installed(self.paths, policy, self.owner)
        self.store.ensure_component(policy.name, policy.validate['tests']['min'] if policy.validate['tests'] else 0)
        self.store.add_release(policy.name, 'baseline', source='installed', healthy=1, deployed_at=self.clock(),
                               deployed_by='install', capabilities=policy.baseline_capabilities)
        self.store.update_component(policy.name, current_release='baseline', degraded=0)
        return {'component': component, 'baseline': 'recorded', 'files': {t['dst']: t['sha256'][:12] for t in manifest['targets']}}

    def recover(self):
        """Доводит прерванные операции: файлы — к прежнему набору, статус — interrupted, запись в журнале операции."""
        from .recover import recover_all
        return recover_all(self)

    # ===================================================================================
    # inspect
    # ===================================================================================
    def inspect(self, component=None):
        names = [component] if component else self.policies.names()
        items = []
        for name in names:
            try:
                items.append(self._inspect_one(self.policies.get(name)))
            except HarnessError as e:
                if component:
                    raise
                items.append({'component': name, **e.to_dict()})
            except Exception as e:  # повреждённое состояние одного компонента не должно скрывать остальные
                if component:
                    raise
                items.append({'component': name, **HarnessError('internal', f'{type(e).__name__}: {str(e)[:200]}').to_dict()})
        out = {'harness': {'version': self.version, 'installed': True, 'policy_problems': self.policies.check_secure()},
               'components': items}
        return out

    def _unit_state(self, unit):
        props = self.system.unit_props(unit, ['ActiveState', 'Result', 'UnitFileState', 'LastTriggerUSec', 'NextElapseUSecRealtime',
                                              'ExecMainStartTimestamp'])
        return {'unit': unit, 'active': props.get('ActiveState'), 'result': props.get('Result') or None,
                'enabled': props.get('UnitFileState') or None,
                'last_run': iso(props.get('LastTriggerUSec') or props.get('ExecMainStartTimestamp')),
                'next_run': iso(props.get('NextElapseUSecRealtime'))}

    def _inspect_one(self, policy):
        comp = self.store.component(policy.name)
        current_id = (comp or {}).get('current_release')
        entry = {'component': policy.name, 'description': policy.description, 'installed': current_id is not None}
        lanes = set()
        if current_id:
            release = self.store.release(policy.name, current_id)
            lanes = set(release['capabilities'].get('lanes', [])) if release and release['capabilities'] else set()
            entry['version'] = {'release': current_id, 'digest': release['digest'], 'commit': release['commit_sha'], 'source': release['source'],
                                'deployed_at': iso(release['deployed_at']), 'deployed_by': release['deployed_by'], 'tests': release['tests']}
            try:
                manifest = releases.load(self.paths, policy.name, current_id)
                files = [{'dst': t['dst'], 'expected': t['sha256'], 'actual': activate.current_sha(self.paths, t['dst'])} for t in manifest['targets']]
                for f in files:
                    f['ok'] = f['expected'] == f['actual']
                entry['drift'] = {'clean': all(f['ok'] for f in files), 'files': files}
            except HarnessError as e:
                entry['drift'] = {'clean': None, 'reason': e.reason}
        else:
            entry['version'] = None
            entry['drift'] = {'clean': None, 'reason': 'baseline не записан'}
        entry['locked'] = bool(comp and comp['degraded'])
        entry['units'] = [self._unit_state(u) for u in self._all_units(policy)]
        last = self.store.last_op(policy.name)
        if last:
            err = last['error'] or {}
            entry['last_operation'] = {'id': last['id'], 'verb': last['verb'], 'status': last['status'], 'at': iso(last['updated_at']),
                                       'reason': err.get('primary_reason') or err.get('reason') or (last['result'] or {}).get('release')}
        else:
            entry['last_operation'] = None
        allowed = ['validate']
        blockers = {}
        if not entry['installed']:
            blockers['deploy'] = blockers['rollback'] = 'not_installed: нет baseline'
        else:
            if entry['locked']:
                blockers['deploy'] = 'locked_degraded: нужен rollback'
            else:
                allowed.append('deploy')
            allowed.append('rollback')
        entry['allowed_operations'] = allowed
        entry['blocked_operations'] = blockers
        entry['dependencies'] = self._dependencies(policy)
        entry['health'] = self._passive_health(policy, lanes) if entry['installed'] else {'ok': None, 'checks': []}
        return entry

    def _passive_health(self, policy, lanes):
        checks = self.health.evaluate(policy, lanes, 0)
        return {'ok': all(c['state'] == 'pass' for c in checks),
                'checks': [{'name': c['name'], 'ok': c['state'] == 'pass', 'detail': c['detail']} for c in checks]}

    def _dependencies(self, policy):
        deps = policy.dependencies
        out = []
        for tool in deps['tools']:
            out.append({'name': f'инструмент {tool}', 'ok': shutil.which(tool, path=SERVICE_PATH) is not None})
        for f in deps['fresh_files']:
            path = f.get('path')
            detail = None
            try:
                if f.get('path_from_json'):
                    src = f['path_from_json']
                    path = json.loads(safefile.read_text(self.paths.host(src['file'])))[src['key']]
                age = self.clock() - self.paths.host(path).stat().st_mtime
                ok = age <= f.get('max_age', 3600)
                detail = f'возраст {int(age)} с'
            except (OSError, ValueError, KeyError, TypeError) as e:
                ok, detail = False, f'нет данных ({type(e).__name__})'
            out.append({'name': f.get('name', 'файл'), 'ok': ok, 'detail': detail})
        for path in deps['state_files']:
            try:
                json.loads(safefile.read_text(self.paths.host(path)))
                ok = True
            except (OSError, ValueError):
                ok = False
            out.append({'name': f'state {path}', 'ok': ok})
        return out

    def _sandbox_check(self, argv):
        """Вспомогательная проверка health: команда в песочнице (не от root). Каталог checks компонента не нужен."""
        limits = {'memory_max': '256M', 'tasks_max': 64, 'runtime_max_sec': 60, 'path': '/usr/local/bin:/usr/bin:/bin'}
        empty = self.paths.work / 'empty'
        empty.mkdir(parents=True, exist_ok=True, mode=0o755)
        outcome, output = sandbox.run(self.system, limits, empty, empty, argv, 60)
        return outcome['ok'], 'ok' if outcome['ok'] else redact(output.strip().splitlines()[-1] if output.strip() else 'нет вывода')[:200]
