"""Приёмка отдельной задачей: метаданные branch/commit, точный SHA, ожидание замка, дедуп и восстановление."""
import copy
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_conveyor import c, sh


class Fixture(unittest.TestCase):
    """Настоящий временный git-репозиторий, подменённые Multica, конфиг, пульт и каталог состояния."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(self.tmp)])
        self.repo = self.tmp / 'service'
        self.repo.mkdir()
        for cmd in (['git', 'init', '-q', '-b', 'main'], ['git', 'config', 'user.email', 't@t'], ['git', 'config', 'user.name', 't']):
            sh(self.repo, *cmd)
        (self.repo / 'a.txt').write_text('a\n')
        sh(self.repo, 'git', 'add', 'a.txt')
        sh(self.repo, 'git', 'commit', '-qm', 'init')
        self.sha = self.commit('t-1-x', 'x.ts')
        self.state = self.tmp / 'state' / 'state.json'
        self.state.parent.mkdir()
        self.controls = self.tmp / 'controls.json'
        self.controls.write_text('{}')
        self.epic = {'key': 'EP-1', 'workspace': 'ws', 'repo': str(self.repo), 'base': 'main', 'squad_id': 'squad',
                     'acceptance': ['test -f x.ts'], 'acceptance_timeout': 60, 'commit_ref': 'REF-1'}
        self.config = self.tmp / 'conveyor.json'
        self.write_config()
        env = {'MULTICA_CONTROL_STATE': str(self.controls), 'MULTICA_CONVEYOR_CONFIG': str(self.config),
               'MULTICA_CONVEYOR_STATE': str(self.state)}
        for p in (patch.dict(os.environ, env), patch.object(c, 'STATE', self.state), patch.object(c, 'CONFIG', self.config),
                  patch.object(c, 'Multica', return_value=self.api)):
            p.start()
            self.addCleanup(p.stop)
        self.issue = {'identifier': 'EP-2', 'title': 'задача', 'status': 'in_review', 'assignee_id': 'agent',
                      'metadata': {'branch': 't-1-x', 'commit': self.sha}}
        self.stages = [{'stage': 1, 'issues': [self.issue]}]
        self.unstaged = []
        self.calls, self.writes, self.launched = [], [], []

    def write_config(self):
        self.config.write_text(json.dumps({'epics': [self.epic]}))

    def commit(self, branch, filename, base='main'):
        sh(self.repo, 'git', 'switch', '-q', *((branch,) if branch == base else ('-C', branch, base)))
        (self.repo / filename).write_text(f'export const v: number = {time.monotonic_ns()}\n')
        sh(self.repo, 'git', 'add', filename)
        sh(self.repo, 'git', 'commit', '-qm', filename)
        sha = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        sh(self.repo, 'git', 'switch', '-q', 'main')
        return sha

    def api(self, *args, **kwargs):
        self.calls.append(args)
        if kwargs.get('write'):
            self.writes.append(args)
        if args[:2] == ('issue', 'children'):
            return {'stages': copy.deepcopy(self.stages), 'unstaged': copy.deepcopy(self.unstaged)}
        return {}

    def tick(self, dry=False, frozen=False):
        w = c.Watch(dry)
        snapshot = {'epics': []}
        c.run_epic(self.epic, w, snapshot, frozen=frozen)
        w.save()
        return w, snapshot

    def launch_inline(self, path):
        """Воркер отрабатывает между тиками: так проверяется сам итог, без atd."""
        self.launched.append(path)
        c.run_job(path)
        return '1'

    def launch_never(self, path):
        self.launched.append(path)
        return '1'

    def job(self, sha=None):
        return c.read_job(c.job_path('EP-2', sha or self.sha, self.head('main')))

    def head(self, ref):
        return subprocess.run(['git', '-C', str(self.repo), 'rev-parse', ref], capture_output=True, text=True).stdout.strip()

    def merged(self, sha):
        return subprocess.run(['git', '-C', str(self.repo), 'merge-base', '--is-ancestor', sha, 'main']).returncode == 0

    def events(self, kind):
        state = json.loads(self.state.read_text()) if self.state.exists() else {}
        return [e['text'] for e in state.get('_events', []) if e['kind'] == kind]


class AcceptTarget(Fixture):
    def test_нет_метаданных_приёмки_нет_и_комментарии_не_читаются(self):
        self.issue['metadata'] = {}
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            _, snapshot = self.tick()
            self.tick()
        self.assertEqual(self.launched, [])
        self.assertFalse(any(a[:3] == ('issue', 'comment', 'list') for a in self.calls))
        self.assertEqual(self.events('wait'), ['EP-1: EP-2 не принимается: в метаданных задачи нет branch и commit'])
        accept = snapshot['epics'][0]['stages'][0]['issues'][0]['accept']
        self.assertEqual(accept['status'], 'blocked')

    def test_ветка_указывает_на_другой_коммит_приёмки_нет(self):
        newer = self.commit('t-1-x', 'y.ts', base='t-1-x')
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
            self.tick()
        self.assertEqual(self.launched, [])
        self.assertEqual(len(self.events('wait')), 1)
        self.assertIn(f'указывает на {newer[:12]}', self.events('wait')[0])
        self.assertFalse(self.merged(self.sha))

    def test_короткий_sha_неизвестный_коммит_и_чужая_ветка_дают_причину(self):
        repo = c.Repo(str(self.repo), 'main')
        cases = {'commit': (self.sha[:7], 'не полный SHA'), 'commit ': ('f' * 40, 'нет в репозитории'),
                 'branch': ('t-9-none', 'ветки `t-9-none` нет'), 'branch ': ('-x', 'недопустимое имя')}
        for field, (value, expected) in cases.items():
            with self.subTest(field=field, value=value):
                meta = {'branch': 't-1-x', 'commit': self.sha, field.strip(): value}
                self.assertIn(expected, c.accept_target({'metadata': meta}, repo)['problem'])

    def test_влитый_коммит_принимать_нечего(self):
        sh(self.repo, 'git', 'merge', '-q', '--no-ff', 't-1-x', '-m', 'merge')
        self.assertIsNone(c.accept_target(self.issue, c.Repo(str(self.repo), 'main')))


class AcceptanceBlockers(Fixture):
    def setUp(self):
        super().setUp()
        self.issue['metadata'] = {}
        self.epic['lead_id'] = '11111111-1111-4111-8111-111111111111'
        self.bodies = []
        self.fail_delivery = False
        original = self.api

        def api(*args, **kwargs):
            if args[:3] == ('issue', 'comment', 'add'):
                self.bodies.append(Path(args[args.index('--content-file') + 1]).read_text())
                if self.fail_delivery:
                    raise RuntimeError('CLI недоступен')
            return original(*args, **kwargs)

        self.api = api
        c.Multica.return_value = api

    def comments(self):
        return [a for a in self.writes if a[:3] == ('issue', 'comment', 'add')]

    def test_старый_блокер_из_журнала_доставляется_лидеру_один_раз(self):
        # Состояние после обновления: причина уже записана, но никому не доставлена.
        self.state.write_text(json.dumps({'_accept_problems': {'EP-2': 'в метаданных задачи нет branch и commit'}}))
        self.tick()
        self.tick()  # новый Watch читает сохранённое состояние после перезапуска
        self.assertEqual(len(self.comments()), 1)
        self.assertIn('mention://agent/' + self.epic['lead_id'], self.bodies[0])
        self.assertIn('branch', self.bodies[0])
        self.assertIn('commit', self.bodies[0])
        self.assertFalse(any(a[:2] == ('issue', 'update') for a in self.writes))
        self.assertFalse(self.merged(self.sha))

    def test_смена_причины_и_повторное_возникновение_сообщаются(self):
        self.tick()
        self.issue['metadata'] = {'branch': 't-1-x', 'commit': 'f' * 40}
        self.tick()
        self.tick()
        self.assertEqual(len(self.comments()), 2)
        self.issue['status'] = 'in_progress'
        self.tick()  # сняли со сдачи, инцидент завершён
        self.issue['status'] = 'in_review'
        self.tick()
        self.assertEqual(len(self.comments()), 3)

    def test_ошибка_доставки_не_теряет_уведомление_и_не_блокирует_приёмку_другой_задачи(self):
        ready = {**copy.deepcopy(self.issue), 'identifier': 'EP-3',
                 'metadata': {'branch': 't-1-x', 'commit': self.sha}}
        self.unstaged = [ready]
        self.fail_delivery = True
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(self.comments(), [])
        self.fail_delivery = False
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
            self.tick()
        self.assertEqual(len(self.comments()), 1)
        self.assertEqual(len(self.bodies), 2)

    def test_пауза_и_dry_run_не_отправляют_и_не_помечают_уведомление(self):
        self.tick(dry=True)
        self.tick(frozen=True)
        self.assertEqual(self.writes, [])
        self.tick()
        self.assertEqual(len(self.comments()), 1)

    def test_блокер_получает_исполнитель_задачи_а_не_лидер(self):
        self.issue.update(assignee_type='agent', assignee_id='22222222-2222-4222-8222-222222222222')
        self.tick()
        self.assertEqual(len(self.comments()), 1)
        self.assertIn('mention://agent/22222222-2222-4222-8222-222222222222', self.bodies[0])
        self.assertNotIn(self.epic['lead_id'], self.bodies[0])

    def test_красную_приёмку_получает_исполнитель_задача_на_скваде_лидеру(self):
        self.issue['metadata'] = {'branch': 't-1-x', 'commit': self.sha}
        self.epic['acceptance'] = ['exit 3']
        self.write_config()
        self.issue.update(assignee_type='agent', assignee_id='22222222-2222-4222-8222-222222222222')
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.tick()
            self.tick()
        self.assertEqual(len(self.comments()), 1)
        self.assertIn('mention://agent/22222222-2222-4222-8222-222222222222', self.bodies[0])
        self.assertIn('metadata `commit`', self.bodies[0])
        self.assertNotIn(self.epic['lead_id'], self.bodies[0])
        self.assertIn(('issue', 'update', 'EP-2', '--status', 'in_progress'), self.writes)

        squad = {**copy.deepcopy(self.issue), 'identifier': 'EP-3', 'assignee_type': 'squad', 'assignee_id': 'squad'}
        self.stages = [{'stage': 1, 'issues': [squad]}]
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.tick()
            self.tick()
        self.assertEqual(len(self.comments()), 2)
        self.assertIn('mention://agent/' + self.epic['lead_id'], self.bodies[1])

    def test_без_этапа_тоже_сообщается_а_закрытая_задача_не_будится(self):
        self.stages = []
        self.unstaged = [self.issue]
        self.tick()
        self.assertEqual(len(self.comments()), 1)
        self.issue.update(status='done', metadata={'branch': 't-1-x'})
        self.tick()
        self.assertEqual(len(self.comments()), 1)


class AcceptJobs(Fixture):
    def test_зелёная_приёмка_вливает_ровно_проверенный_коммит(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.tick()
            self.assertEqual(self.job()['status'], 'passed')
            self.tick()
        self.assertTrue(self.merged(self.sha))
        self.assertIn(('issue', 'update', 'EP-2', '--status', 'done'), self.writes)
        self.assertIn(f"Merge branch 't-1-x'. REF-1", subprocess.run(['git', '-C', str(self.repo), 'log', '-1', '--format=%s'],
                                                                     capture_output=True, text=True).stdout)

    def test_новая_проверка_стартует_после_слияния_готовой(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.tick()
        self.assertEqual(self.job()['status'], 'passed')
        other = self.commit('t-1-y', 'y.ts')
        self.stages = [{'stage': 1, 'issues': [{**copy.deepcopy(self.issue), 'identifier': 'EP-3',
                                                'metadata': {'branch': 't-1-y', 'commit': other}}, self.issue]}]
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
        self.assertTrue(self.merged(self.sha))
        started = [c.read_job(p) for p in self.launched if p.name.startswith('EP-3')]
        self.assertEqual([j['base_sha'] for j in started], [self.head('main')])

    def test_повтор_тика_и_перезапуск_сторожа_не_дублируют_задачу(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            for _ in range(3):
                self.tick()  # каждый тик — новый Watch, как после перезапуска юнита
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(self.job()['status'], 'queued')
        self.assertEqual(len(self.events('accept')), 1)

    def test_итог_после_перезапуска_берётся_из_файла_задачи(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
        c.run_job(self.launched[0])  # воркер доработал, пока сторож был остановлен
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
        self.assertEqual(len(self.launched), 1)
        self.assertTrue(self.merged(self.sha))

    def test_новый_sha_требует_новой_проверки(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.epic['acceptance'] = ['false']
            self.write_config()
            self.tick()
            self.tick()
            self.assertEqual(self.job()['status'], 'failed')
            fixed = self.commit('t-1-x', 'fix.ts', base='t-1-x')
            self.issue['metadata']['commit'] = fixed
            self.epic['acceptance'] = ['true']
            self.write_config()
            self.tick()
            self.tick()
        self.assertEqual(len(self.launched), 2)
        self.assertEqual(c.read_job(self.launched[1])['sha'], fixed)
        self.assertEqual(c.read_job(self.launched[1])['status'], 'passed')
        self.assertTrue(self.merged(fixed))

    def test_настоящая_ошибка_сохраняет_код_и_лог_и_сообщается_один_раз(self):
        self.epic['acceptance'] = ['echo сломано; exit 3']
        self.write_config()
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            for _ in range(3):
                self.tick()
        job = self.job()
        self.assertEqual((job['status'], job['code']), ('failed', 3))
        self.assertIn('кодом 3', job['reason'])
        self.assertIn('сломано', Path(job['log']).read_text())
        self.assertEqual(sum(a[:3] == ('issue', 'comment', 'add') for a in self.writes), 1)
        self.assertEqual(self.writes.count(('issue', 'update', 'EP-2', '--status', 'in_progress')), 1)
        self.assertFalse(self.merged(self.sha))

    def test_задача_без_этапа_и_задача_следующего_этапа_принимаются(self):
        later = {**copy.deepcopy(self.issue), 'identifier': 'EP-3'}
        unstaged = {**copy.deepcopy(self.issue), 'identifier': 'EP-4'}
        open_ = {'identifier': 'EP-5', 'status': 'in_progress', 'assignee_id': 'agent'}
        new = {'identifier': 'EP-6', 'status': 'backlog', 'assignee_id': None}
        self.stages = [{'stage': 1, 'issues': [open_]}, {'stage': 2, 'issues': [later, new]}]
        self.unstaged = [unstaged]
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            _, snapshot = self.tick()
        # Одна приёмка на эпик за раз; вторая ждёт очереди.
        self.assertEqual([p.name.split('-')[1] for p in self.launched], ['3'])
        self.assertEqual(snapshot['epics'][0]['unstaged'][0]['accept']['status'], 'queued')
        # Назначение по этапам прежнее: стадия 2 ждёт, пока открыта стадия 1.
        self.assertFalse(any(a[:2] == ('issue', 'assign') for a in self.writes))
        c.run_job(self.launched[0])
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.tick()
            self.tick()
        self.assertEqual(sorted(p.name.split('-')[1] for p in self.launched), ['3', '4'])

    def test_пропавший_воркер_перезапускается_и_ограничен(self):
        now = c.now_utc()
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
            path = self.launched[0]
            for attempt in range(2, c.JOB_ATTEMPTS + 1):
                job = c.read_job(path)
                job['status'] = 'running'  # воркер взял задачу и умер: замок свободен
                c.write_job(path, job)
                self.tick()
                self.assertEqual(c.read_job(path)['attempts'], attempt)
            job = c.read_job(path)
            job['queued_at'] = (now - dt.timedelta(seconds=c.JOB_LOST_AFTER + 1)).isoformat()
            c.write_job(path, job)
            self.tick()
        self.assertEqual(len(self.launched), c.JOB_ATTEMPTS)
        self.assertEqual(c.read_job(path)['status'], 'failed')
        self.assertEqual(sum(a[:3] == ('issue', 'comment', 'add') for a in self.writes), 1)

    def test_живой_воркер_не_перезапускается(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
            path = self.launched[0]
            job = c.read_job(path)
            job.update(status='running', queued_at='2000-01-01T00:00:00+00:00')
            c.write_job(path, job)
            with c.job_lock(path) as held:
                self.assertTrue(held)
                self.tick()
        self.assertEqual(len(self.launched), 1)

    def test_dry_run_не_запускает(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick(dry=True)
        self.assertEqual(self.launched, [])
        self.assertFalse(c.jobs_dir().exists())


class LockWait(Fixture):
    def busy_then_ok(self, busy):
        counter = self.tmp / 'n'
        return f'n=$(cat {counter} 2>/dev/null || echo 0); echo $((n+1)) > {counter}; [ "$n" -ge {busy} ] || exit 75'

    def test_ожидание_замка_не_входит_в_таймаут(self):
        repo = c.Repo(str(self.repo), 'main')
        states = []
        started = time.monotonic()
        res = repo.accept(self.sha, [self.busy_then_ok(3)], 1, key='EP-2', busy_codes=(75,), wait_poll=0.6, wait_max=30,
                          on_state=states.append)
        self.assertGreater(time.monotonic() - started, 1.5)  # ждали дольше таймаута команды
        self.assertEqual(res['status'], 'passed', res['reason'])
        self.assertEqual(states.count('waiting'), 3)
        self.assertIn('общий ресурс занят', Path(res['log']).read_text())

    def test_не_дождалась_замка_приёмка_отложена_а_не_провалена(self):
        self.epic.update(acceptance=['exit 75'], acceptance_wait_poll=0.1, acceptance_wait_max=0.3)
        self.write_config()
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.tick()
            self.tick()
        job = self.job()
        self.assertEqual((job['status'], job['code']), ('deferred', 75))
        self.assertFalse(any(a[:3] == ('issue', 'comment', 'add') for a in self.writes))
        self.assertFalse(any(a[:2] == ('issue', 'update') for a in self.writes))
        self.assertEqual(len(self.events('wait')), 1)
        self.assertEqual(self.events('fail'), [])
        # Через acceptance_retry_minutes та же задача (та же пара коммитов) пробует снова — и проходит.
        self.epic.update(acceptance=['true'], acceptance_retry_minutes=0)
        self.write_config()
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.tick()
            self.tick()
        self.assertEqual(len(self.launched), 2)
        self.assertEqual(len({p.name for p in self.launched}), 1)
        self.assertTrue(self.merged(self.sha))

    def test_команды_по_умолчанию_не_ждут_замок_сами(self):
        self.epic['acceptance'] = ['test "$E2E_LOCK_WAIT" = 0']
        self.write_config()
        with patch.object(c, 'launch_job', side_effect=self.launch_inline):
            self.tick()
        self.assertEqual(self.job()['status'], 'passed')


class Worker(Fixture):
    def test_пауза_откладывает_проверку(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
        self.controls.write_text(json.dumps({'targets': {'EP-1': {'paused': True}}}))
        c.run_job(self.launched[0])
        self.assertEqual(c.read_job(self.launched[0])['status'], 'deferred')

    def test_эпик_убран_из_конфига(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
        self.config.write_text(json.dumps({'epics': []}))
        c.run_job(self.launched[0])
        self.assertEqual(c.read_job(self.launched[0])['status'], 'failed')

    def test_занятый_замок_задачи_второй_воркер_не_запускает(self):
        with patch.object(c, 'launch_job', side_effect=self.launch_never):
            self.tick()
        path = self.launched[0]
        with c.job_lock(path) as held, patch.object(c, 'JOB_LOCK_WAIT', 0.3):
            self.assertTrue(held)
            c.run_job(path)
        self.assertEqual(c.read_job(path)['status'], 'queued')


class DetachedJob(Fixture):
    """Настоящий запуск через `at`: тик не ждёт длинную проверку."""

    def setUp(self):
        super().setUp()
        tools = self.tmp / 'bin'
        tools.mkdir()
        self.at_calls = self.tmp / 'at-calls'
        at = tools / 'at'
        # Подмена atd: принять задачу и выполнить её отдельно от вызывающего, как atd.
        at.write_text(f'#!/bin/sh\necho "$@" >> {self.at_calls}\nf=$(mktemp {self.tmp}/at-job.XXXXXX)\ncat > "$f"\n'
                      f'setsid sh "$f" </dev/null >/dev/null 2>&1 &\necho "job 7 at now" >&2\n')
        at.chmod(0o755)
        p = patch.dict(os.environ, {'PATH': f'{tools}:{os.environ.get("PATH", "/usr/bin:/bin")}'})
        p.start()
        self.addCleanup(p.stop)

    def wait_final(self, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.job()
            if job and job['status'] not in c.JOB_ACTIVE:
                return job
            time.sleep(0.2)
        self.fail(f'задача приёмки не закончилась: {self.job()}')

    def test_длинная_проверка_не_держит_тик(self):
        self.epic['acceptance'] = ['sleep 3', 'test -f x.ts']
        self.write_config()
        started = time.monotonic()
        self.tick()
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertIn(self.job()['status'], c.JOB_ACTIVE)
        self.tick()  # повтор тика, пока проверка идёт
        self.assertEqual(len(self.at_calls.read_text().splitlines()), 1)
        job = self.wait_final()
        self.assertEqual(job['status'], 'passed', job.get('reason'))
        self.tick()
        self.assertTrue(self.merged(self.sha))
        self.assertEqual(len(self.at_calls.read_text().splitlines()), 1)

    def test_временный_каталог_запустившего_рана_не_нужен_проверке(self):
        # Тик вручную из рана агента: atd сохраняет его TMPDIR, а демон удаляет этот каталог по концу рана.
        run_tmp = self.tmp / 'multica-task-1'
        run_tmp.mkdir()
        self.epic['acceptance'] = ['sleep 2', 'test -f x.ts']
        self.write_config()
        with patch.dict(os.environ, {'TMPDIR': str(run_tmp), 'TMP': str(run_tmp), 'TEMP': str(run_tmp)}):
            self.tick()
        time.sleep(1)
        subprocess.run(['rm', '-rf', str(run_tmp)], check=True)
        job = self.wait_final()
        self.assertEqual(job['status'], 'passed', job.get('reason'))

    def test_задача_atd_не_наследует_временный_каталог_и_cwd_рана(self):
        path = c.jobs_dir() / 'EP-2-abc.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.CompletedProcess(['at', 'now'], 0, '', 'job 9 at now\n')
        with patch.dict(os.environ, {'TMPDIR': '/tmp/multica-task-1', 'TMP': '/x', 'TEMP': '/x'}), \
                patch.object(c.subprocess, 'run', return_value=done) as run:
            self.assertEqual(c.launch_job(path), '9')
        kw = run.call_args.kwargs
        self.assertFalse({'TMPDIR', 'TMP', 'TEMP'} & set(kw['env']))
        self.assertEqual(kw['cwd'], str(path.parent))


if __name__ == '__main__':
    unittest.main()
