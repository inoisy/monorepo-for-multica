import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

path = str(Path(__file__).resolve().parent.parent / 'multica-conveyor')
spec = importlib.util.spec_from_loader('conveyor', importlib.machinery.SourceFileLoader('conveyor', path))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def issue(key, status='backlog', assignee=None, desc=''):
    return {'identifier': key, 'status': status, 'status_category': status, 'assignee_id': assignee, 'description': desc}


def keys(issues): return [i['identifier'] for i in issues]


class Decide(unittest.TestCase):
    def test_первая_стадия_с_незакрытой_задачей(self):
        stages = [{'stage': 1, 'issues': [issue('A', 'in_progress', 'sq')]},
                  {'stage': 2, 'issues': [issue('B'), issue('C')]}]
        self.assertEqual(c.decide(stages), (1, [], [], []))

    def test_закрытая_стадия_открывает_следующую(self):
        stages = [{'stage': 2, 'issues': [issue('B'), issue('C')]},
                  {'stage': 1, 'issues': [issue('A', 'done', 'sq')]}]
        stage, _, to_assign, held = c.decide(stages)
        self.assertEqual((stage, keys(to_assign), held), (2, ['B', 'C'], []))

    def test_назначенная_задача_не_назначается_повторно(self):
        stages = [{'stage': 1, 'issues': [issue('A', 'todo', 'sq'), issue('B')]}]
        self.assertEqual(keys(c.decide(stages)[2]), ['B'])

    def test_ждущая_заказчика_пропускается_и_держит_стадию(self):
        stages = [{'stage': 1, 'issues': [issue('A', 'done', 'sq')]},
                  {'stage': 2, 'issues': [issue('B', desc='**Ждёт:** ответа'), issue('C')]},
                  {'stage': 3, 'issues': [issue('D')]}]
        stage, _, to_assign, held = c.decide(stages)
        self.assertEqual((stage, keys(to_assign), keys(held)), (2, ['C'], ['B']))

    def test_отменённая_считается_закрытой(self):
        stages = [{'stage': 1, 'issues': [issue('A', 'cancelled')]}, {'stage': 2, 'issues': [issue('B')]}]
        self.assertEqual(keys(c.decide(stages)[2]), ['B'])

    def test_эпик_закрыт(self):
        self.assertEqual(c.decide([{'stage': 1, 'issues': [issue('A', 'done', 'sq')]}]), (None, [], [], []))


class Merge(unittest.TestCase):
    def test_невлитая_задача_в_готово_держит_стадию_и_идёт_на_приёмку(self):
        stages = [{'stage': 1, 'issues': [issue('A', 'done', 'sq')]}, {'stage': 2, 'issues': [issue('B')]}]
        c.mark_unmerged(stages, lambda i: ['t-12345-p1'], lambda b: False)
        stage, to_accept, to_assign, _ = c.decide(stages)
        self.assertEqual((stage, keys(to_accept), to_assign), (1, ['A'], []))

    def test_сданная_задача_идёт_на_приёмку(self):
        stages = [{'stage': 1, 'issues': [issue('A', 'in_review', 'sq')]}]
        c.mark_unmerged(stages, lambda i: ['t-12345-p1'], lambda b: False)
        self.assertEqual(keys(c.decide(stages)[1]), ['A'])

    def test_задача_в_работе_на_приёмку_не_идёт(self):
        stages = [{'stage': 1, 'issues': [issue('A', 'in_progress', 'sq')]}]
        c.mark_unmerged(stages, lambda i: ['t-12345-p1'], lambda b: False)
        self.assertEqual(c.decide(stages)[1], [])

    def test_влитая_задача_открывает_следующую(self):
        stages = [{'stage': 1, 'issues': [issue('A', 'done', 'sq')]}, {'stage': 2, 'issues': [issue('B')]}]
        c.mark_unmerged(stages, lambda i: ['t-12345-p1'], lambda b: True)
        self.assertEqual(keys(c.decide(stages)[2]), ['B'])

    def test_ветка_в_тексте_находится(self):
        self.assertEqual(c.BRANCH.findall('Ветка t-12345-p1-skeleton, коммит 7b5473d; REF-12345.'), ['t-12345-p1-skeleton'])

    def test_проверка_диффа(self):
        self.assertTrue(c.DIFF_GUARD.search('+const x: any = 1'))
        self.assertTrue(c.DIFF_GUARD.search('+// @ts-ignore'))
        self.assertFalse(c.DIFF_GUARD.search('-const x: any = 1\n+const x: number = 1'))

    def test_провал_на_тех_же_коммитах_не_повторяется(self):
        st = {'A': {'t-1-x': 'b1+m1'}}
        self.assertTrue(c.already_failed(st, 'A', 't-1-x', 'b1+m1'))
        self.assertFalse(c.already_failed(st, 'A', 't-1-x', 'b2+m1'))


def sh(cwd, *cmd): subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


class RepoAcceptance(unittest.TestCase):
    """Приёмка и слияние на настоящем временном git-репозитории."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        state = patch.object(c, 'STATE', Path(self.tmp) / 'state' / 'state.json')  # логи приёмки не в боевой каталог
        state.start()
        self.addCleanup(state.stop)
        self.repo = os.path.join(self.tmp, 'service')
        os.mkdir(self.repo)
        for cmd in (['git', 'init', '-q', '-b', 'main'], ['git', 'config', 'user.email', 't@t'], ['git', 'config', 'user.name', 't']):
            sh(self.repo, *cmd)
        Path(self.repo, 'a.txt').write_text('a\n')
        sh(self.repo, 'git', 'add', 'a.txt')
        sh(self.repo, 'git', 'commit', '-qm', 'init')
        self.r = c.Repo(self.repo, 'main')

    def branch(self, name, filename, content):
        sh(self.repo, 'git', 'switch', '-qc', name)
        Path(self.repo, filename).write_text(content)
        sh(self.repo, 'git', 'add', filename)
        sh(self.repo, 'git', 'commit', '-qm', name)
        sh(self.repo, 'git', 'switch', '-q', 'main')

    def test_зелёная_ветка_вливается(self):
        self.branch('t-1-ok', 'ok.ts', 'export const x: number = 1\n')
        ok, why, _ = self.r.accept('t-1-ok', ['test -f ok.ts'], 60)
        self.assertTrue(ok, why)
        self.r.merge('t-1-ok', 'REF-1')
        self.assertTrue(self.r.merged('t-1-ok'))

    def test_красная_команда_не_вливается(self):
        self.branch('t-1-red', 'red.ts', 'export const y = 2\n')
        ok, why, _ = self.r.accept('t-1-red', ['false'], 60)
        self.assertFalse(ok)
        self.assertIn('`false`', why)
        self.assertFalse(self.r.merged('t-1-red'))

    def test_any_в_диффе_не_вливается(self):
        self.branch('t-1-any', 'any.ts', 'export const z: any = 3\n')
        ok, why, _ = self.r.accept('t-1-any', ['true'], 60)
        self.assertFalse(ok)
        self.assertIn('any', why)

    def test_конфликт_с_main(self):
        self.branch('t-1-conf', 'a.txt', 'ветка\n')
        Path(self.repo, 'a.txt').write_text('main\n')
        sh(self.repo, 'git', 'commit', '-qam', 'main меняет a')
        ok, why, _ = self.r.accept('t-1-conf', ['true'], 60)
        self.assertFalse(ok)
        self.assertIn('конфликт', why)


class Providers(unittest.TestCase):
    now = c.ts('2026-10-16T10:00:00Z')
    quota = {'status': 'failed', 'failure_reason': 'agent_error.provider_quota_limit', 'created_at': '2026-10-16T09:50:00Z'}
    ok = {'status': 'completed', 'created_at': '2026-10-16T09:55:00Z'}

    def test_лимит_на_основном_переезжает_на_следующий(self):
        self.assertEqual(c.provider_decision([self.quota], {'idx': 0, 'since': None}, 3, self.now, 5), ('switch', 1))

    def test_лимит_на_запасном_переезжает_дальше(self):
        self.assertEqual(c.provider_decision([self.quota], {'idx': 1, 'since': '2026-10-16T09:00:00+00:00'}, 3, self.now, 5), ('switch', 2))

    def test_старое_падение_до_переезда_не_считается(self):
        self.assertIsNone(c.provider_decision([self.quota], {'idx': 1, 'since': '2026-10-16T09:55:00+00:00'}, 3, self.now, 5))

    def test_вся_цепочка_исчерпана(self):
        self.assertEqual(c.provider_decision([self.quota], {'idx': 2, 'since': '2026-10-16T09:00:00+00:00'}, 3, self.now, 5), ('exhausted', 2))

    def test_через_5_часов_возврат_на_основной(self):
        self.assertEqual(c.provider_decision([self.ok], {'idx': 1, 'since': '2026-10-16T04:30:00+00:00'}, 3, self.now, 5), ('restore', 0))

    def test_рано_возвращаться(self):
        self.assertIsNone(c.provider_decision([self.ok], {'idx': 1, 'since': '2026-10-16T08:00:00+00:00'}, 3, self.now, 5))

    def test_успешный_ран_на_основном_ничего(self):
        self.assertIsNone(c.provider_decision([self.ok, self.quota], {'idx': 0, 'since': None}, 3, self.now, 5))

    def test_json_с_хвостом_подсказки(self):
        self.assertEqual(c.parse_json('[{"a": 1}]\nMore runs available; use --before x'), [{'a': 1}])
        self.assertEqual(c.parse_json('Comment added'), {})

    def test_страница_экранирует_и_рисуется(self):
        snap = {'tick': '2026-10-16 10:00:00', 'errors': [], 'quotas': [{'name': 'Codex', 'line': 'main=[9 64]'}],
                'epics': [{'key': 'TASK-1', 'name': 'Эпик', 'stage': 1, 'stages': [{'stage': 1, 'issues': [
                    {'key': 'TASK-2', 'title': '<script>x</script>', 'status': 'in_progress', 'assigned': True, 'held': False, 'unmerged': [],
                     'jobs': [{'agent': 'Аналитик', 'status': 'completed', 'at': '2026-10-16T09:00:00Z', 'secs': 240, 'quota': False},
                              {'agent': 'Бэкенд', 'status': 'failed', 'at': '2026-10-16T09:10:00Z', 'secs': 5, 'quota': True}]}]}]}],
                'agents': [{'name': 'Бэкенд', 'idx': 1, 'chain_len': 3, 'runtime': 'Claude · 2 подписки', 'model': 'claude-opus-5-5',
                            'since': '2026-10-16T09:00:00+00:00', 'last_status': 'running', 'last_at': '2026-10-16T09:59:00Z'}]}
        page = c.render(snap, [{'t': '2026-10-16T09:00:00+00:00', 'kind': 'provider', 'text': 'Бэкенд: лимит, переезжает'}])
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>x', page)
        self.assertIn('запасной 1', page)
        self.assertIn('переезжает', page)
        self.assertIn('Этап 1', page)
        self.assertIn('Джобы активного этапа', page)
        self.assertIn('4 мин 0 с', page)
        self.assertIn('лимит', page)
        self.assertIn('приёмка и слияние', page)

    def test_раны_в_джобы_по_времени(self):
        runs = [{'agent_id': 'b', 'status': 'running', 'created_at': '2026-10-16T09:10:00Z', 'started_at': '2026-10-16T09:10:00Z'},
                {'agent_id': 'a', 'status': 'completed', 'created_at': '2026-10-16T09:00:00Z',
                 'started_at': '2026-10-16T09:00:00Z', 'completed_at': '2026-10-16T09:01:30Z'}]
        jobs = c.jobs_of(runs, {'a': 'Аналитик'})
        self.assertEqual([j['agent'] for j in jobs], ['Аналитик', 'b'])
        self.assertEqual(jobs[0]['secs'], 90)
        self.assertEqual(c.job_state(jobs[1]), 'running')

    def test_статусы_задач_как_в_gitlab(self):
        base = {'held': False, 'unmerged': []}
        self.assertEqual(c.issue_state({**base, 'status': 'done'}), 'success')
        self.assertEqual(c.issue_state({**base, 'status': 'in_review'}), 'review')
        self.assertEqual(c.issue_state({**base, 'status': 'backlog', 'held': True}), 'paused')
        self.assertEqual(c.short_title('Ресурсное планирование: 6. Согласование заявки. ' + 'T' + '-12345'), '6. Согласование заявки.')


class ControlledProviders(unittest.TestCase):
    now = c.ts('2026-10-16T10:00:00Z')
    quota = {'status': 'failed', 'created_at': '2026-10-16T09:50:00Z', 'error': 'quota'}
    ok = {'status': 'completed', 'created_at': '2026-10-16T09:55:00Z'}

    def test_ручной_режим_не_переключается_на_лимите(self):
        self.assertIsNone(c.provider_decision([self.quota], {'idx': 0}, 3, self.now, 5, mode='manual'))

    def test_исчерпанный_резерв_пропускается(self):
        self.assertEqual(c.provider_decision([self.quota], {'idx': 0}, 3, self.now, 5,
                         availability=[True, False, True]), ('switch', 2))

    def test_при_активном_ране_возврата_нет(self):
        runs = [{'status': 'running', 'created_at': '2026-10-16T09:50:00Z'}]
        self.assertIsNone(c.provider_decision(runs, {'idx': 1, 'since': '2026-10-16T01:00:00Z'}, 3, self.now, 5))

    def test_все_квоты_исчерпаны_ждём(self):
        self.assertEqual(c.provider_decision([self.quota], {'idx': 0}, 3, self.now, 5,
                         availability=[False, False, False]), ('exhausted', 0))

    def test_последний_резерв_упал_но_основной_доступен(self):
        self.assertEqual(c.provider_decision([self.quota], {'idx': 2}, 3, self.now, 5,
                         availability=[True, False, False]), ('switch', 0))

    def test_основной_освободился_раньше_5_часов_возврат(self):
        self.assertEqual(c.provider_decision([self.ok], {'idx': 3, 'since': '2026-10-16T09:00:00Z'}, 4, self.now, 5,
                         availability=[False, False, True, True]), ('restore', 2))

    def test_свежий_переезд_не_дёргаем_обратно(self):
        self.assertIsNone(c.provider_decision([self.ok], {'idx': 2, 'since': '2026-10-16T09:45:00Z'}, 3, self.now, 5,
                                              availability=[True, False, True]))

    def test_неизвестная_квота_не_повод_возвращаться_раньше(self):
        self.assertIsNone(c.provider_decision([self.ok], {'idx': 1, 'since': '2026-10-16T08:00:00Z'}, 3, self.now, 5,
                                              availability=[None, True, True]))

    def test_возврат_на_исчерпанный_основной_не_происходит(self):
        self.assertIsNone(c.provider_decision([], {'idx': 1, 'since': '2026-10-16T01:00:00Z'}, 3,
                                            self.now, 5, availability=[False, True, True]))


class MetaControl(unittest.TestCase):
    def test_пауза_блокирует_запись_до_запуска_CLI(self):
        from unittest.mock import patch
        guard = lambda: (_ for _ in ()).throw(c.AutomationPaused('пауза'))
        with patch.object(c.subprocess, 'run') as run:
            with self.assertRaises(c.AutomationPaused):
                c.Multica('workspace', False, guard)('issue', 'rerun', 'TASK-1', write=True)
            run.assert_not_called()

    def test_выбор_целей_исключает_отключённый_эпик(self):
        cfg = {'epics': [{'key': 'TASK-1', 'workspace': 'ws', 'repo': '/safe/repo'}]}
        targets = c.control.targets(cfg, {'targets': {'TASK-1': {'enabled': False},
                  'TASK-2': {'key': 'TASK-2', 'enabled': True, 'kind': 'issue', 'workspace': 'ws', 'name': 'Задача'}}})
        self.assertFalse(targets[0]['enabled'])
        self.assertEqual(targets[0]['repo'], '/safe/repo')
        self.assertEqual(targets[1]['kind'], 'issue')


class MetaExecution(unittest.TestCase):
    def test_пауза_не_запускает_автоматические_шаги(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            controls = str(Path(tmp) / 'controls.json')
            Path(controls).write_text(json.dumps({'paused': True}))
            cfg = {'epics': [{'key': 'TASK-1'}], 'status_dir': tmp}
            with patch.dict(os.environ, {'MULTICA_CONTROL_STATE': controls}), \
                    patch.object(c, 'STATE', Path(tmp) / 'state.json'), \
                    patch.object(c, 'run_epic') as epic, patch.object(c, 'run_providers') as providers, \
                    patch.object(c, 'run_stands') as stands:
                c.run(cfg, False)
                # На паузе эпик только наблюдается — для доски пульта.
                self.assertTrue(epic.call_args.kwargs['frozen'])
                providers.assert_not_called()
                stands.assert_not_called()
            self.assertTrue(json.loads(Path(tmp, 'status.json').read_text())['paused'])

    def test_строка_эпика_публикуется_до_долгой_приёмки(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            controls = str(Path(tmp) / 'controls.json')
            Path(controls).write_text('{}')
            status = Path(tmp, 'status.json')
            status.write_text(json.dumps({'tick': 'old', 'epics': [], 'agents': [], 'quotas': [], 'errors': []}))
            cfg = {'epics': [{'key': 'TASK-1', 'workspace': 'ws', 'repo': '/r'}], 'status_dir': tmp}
            seen = {}
            issue = {'identifier': 'TASK-2', 'title': 'готова к приёмке', 'status': 'in_review', 'assignee_id': 'a', 'unmerged': ['b']}

            def api(*args, **kwargs):
                if args[:2] == ('issue', 'children'):
                    return {'stages': [{'stage': 1, 'issues': [issue]}],
                            'unstaged': [{'identifier': 'TASK-3', 'title': 'новая', 'status': 'todo'}]}
                return {}

            def accept(*args, **kwargs):
                # Приёмка идёт — страница уже показывает свежие задачи эпика.
                page = json.loads(status.read_text())
                seen['keys'] = [i['key'] for e in page['epics'] for st in e['stages'] for i in st['issues']] + \
                               [i['key'] for e in page['epics'] for i in e['unstaged']]
                return False

            with patch.dict(os.environ, {'MULTICA_CONTROL_STATE': controls}), \
                    patch.object(c, 'STATE', Path(tmp) / 'state.json'), patch.object(c, 'Multica', return_value=api), \
                    patch.object(c, 'Repo'), patch.object(c, 'mark_unmerged'), patch.object(c, 'accept_issue', side_effect=accept), \
                    patch.object(c, 'run_providers'), patch.object(c, 'run_stands'), patch.object(c, 'quotas', return_value=[]):
                c.run(cfg, False)
            self.assertEqual(sorted(seen['keys']), ['TASK-2', 'TASK-3'])

    def test_ветки_задачи_берутся_из_последнего_отчёта_а_не_из_упоминаний(self):
        def comment(at, text, who='agent'):
            return {'created_at': at, 'author_type': who, 'content': text}
        comments = [
            comment('16:04', 'Ветка `t-12345-assignments-list`. Не трогает `t-12345-header-kpi` и t-12345-qa-fixture-f0'),
            comment('18:44', 'Итог: прошло, ветка `t-12345-assignments-list`, коммит 947e7d1'),
            comment('19:36', 'Автоприёмка упала: ветка `t-12345-header-kpi`, таймаут'),
            comment('19:40', 'ветка `t-12345-other`', who='member'),
        ]
        self.assertEqual(c.report_branches(comments), ['t-12345-assignments-list'])
        # Без «ветка `…`» работает прежнее правило — любые упоминания агентов.
        self.assertEqual(c.report_branches([comment('1', 'сдано в t-5-fix-a и t-5-fix-b')]), ['t-5-fix-a', 't-5-fix-b'])

    def test_пауза_цели_морозит_только_её(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            controls = str(Path(tmp) / 'controls.json')
            Path(controls).write_text(json.dumps({'targets': {'TASK-1': {'paused': True}}}))
            cfg = {'epics': [{'key': 'TASK-1'}, {'key': 'TASK-5'}], 'status_dir': tmp}
            with patch.dict(os.environ, {'MULTICA_CONTROL_STATE': controls}), \
                    patch.object(c, 'STATE', Path(tmp) / 'state.json'), \
                    patch.object(c, 'run_epic') as epic, patch.object(c, 'run_providers'), patch.object(c, 'run_stands'):
                c.run(cfg, False)
            frozen = {call.args[0]['key']: call.kwargs['frozen'] for call in epic.call_args_list}
            self.assertEqual(frozen, {'TASK-1': True, 'TASK-5': False})

    def test_снятая_цель_не_обрабатывается(self):
        cfg = {'epics': [{'key': 'TASK-1', 'workspace': 'ws'}]}
        self.assertEqual(c.control.targets(cfg, {'targets': {'TASK-1': {'removed': True}}}), [])

    def test_замороженный_эпик_ничего_не_пишет_но_попадает_в_снимок(self):
        from unittest.mock import Mock, patch
        calls = []
        def api(*args, **kwargs):
            calls.append((args, kwargs))
            if args[:2] == ('issue', 'children'):
                return {'stages': [{'stage': 1, 'issues': [{'identifier': 'TASK-2', 'status': 'todo', 'assignee_id': None}]}]}
            return {}
        snapshot = {'epics': []}
        with patch.object(c, 'Multica', return_value=api):
            c.run_epic({'key': 'TASK-1', 'workspace': 'ws', 'squad_id': 'squad'}, Mock(state={}, dry=False), snapshot, frozen=True)
        self.assertFalse(any(kw.get('write') for _, kw in calls))
        self.assertTrue(snapshot['epics'][0]['paused'])
        self.assertEqual(snapshot['epics'][0]['stages'][0]['issues'][0]['key'], 'TASK-2')

    def test_пауза_после_тестов_не_даёт_слить_ветку(self):
        from unittest.mock import Mock
        repo = Mock()
        repo.head.return_value = 'sha'
        repo.accept.return_value = (True, 'зелёно', '')
        watch = Mock(state={}, dry=False)
        watch.permit.side_effect = [None, c.AutomationPaused('пауза')]
        with self.assertRaises(c.AutomationPaused):
            c.accept_issue(Mock(), repo, {'key': 'TASK-1'},
                           {'identifier': 'TASK-2', 'unmerged': ['t-1-test'], 'status': 'in_review'}, watch)
        repo.merge.assert_not_called()

    def test_отдельная_задача_назначается_без_поиска_детей(self):
        from unittest.mock import Mock, patch
        calls = []
        def api(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('issue', 'get'):
                return {'identifier': 'TASK-1', 'status': 'todo', 'assignee_id': None}
            return {}
        watch = Mock(state={}, dry=False)
        with patch.object(c, 'Multica', return_value=api):
            c.run_epic({'key': 'TASK-1', 'workspace': 'ws', 'kind': 'issue', 'squad_id': 'squad'}, watch, {'epics': []})
        self.assertFalse(any(args[:2] == ('issue', 'children') for args in calls))
        self.assertTrue(any(args[:2] == ('issue', 'assign') for args in calls))


class Stands(unittest.TestCase):
    def test_пустые_справочники_грузим(self):
        self.assertTrue(c.needs_seed({'items': [{'lastSuccessAt': None, 'lastRun': None}]}))
        self.assertTrue(c.needs_seed({'items': []}))

    def test_загрузка_идёт_ждём(self):
        self.assertFalse(c.needs_seed({'items': [{'lastSuccessAt': None, 'lastRun': {'status': 'running'}}]}))

    def test_уже_загружены(self):
        self.assertFalse(c.needs_seed({'items': [{'lastSuccessAt': '2026-10-16T10:05:00Z', 'lastRun': {'status': 'succeeded'}}]}))

    def test_клиент_входит_оператором_и_запускает_загрузку(self):
        import http.server, threading
        calls = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def reply(self, code, body=None, cookie=None):
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                if cookie:
                    self.send_header('Set-Cookie', f'resource_session={cookie}; Path=/; HttpOnly')
                self.end_headers()
                self.wfile.write(json.dumps(body or {}).encode())

            def do_GET(self):
                calls.append(('GET', self.path, self.headers.get('Cookie')))
                if self.headers.get('Cookie') != 'resource_session=tok':
                    return self.reply(401)
                self.reply(200, {'items': [{'lastSuccessAt': None, 'lastRun': None, 'counts': {}}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(('POST', self.path, self.headers.get('x-csrf-token'), self.headers.get('Origin'), body))
                if self.path == '/auth/test/login':
                    return self.reply(200, {'csrfToken': 'csrf1'}, cookie='tok')
                self.reply(202)

        try:
            srv = http.server.HTTPServer(('127.0.0.1', 0), H)
        except OSError as err:  # песочница validate без сетевых семейств сокетов
            self.skipTest(f'локальный сокет недоступен: {err}')
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{srv.server_port}'
        saved = {'cookie': 'old', 'csrf': 'x'}
        st = c.Stand(url, 'op-1', saved)
        code, status = st.authed('GET', '/api/v1/sync/status')
        self.assertEqual(code, 200)
        self.assertTrue(c.needs_seed(status))
        code, _ = st.authed('POST', '/api/v1/sync/sphere', {})
        srv.shutdown()
        srv.server_close()
        self.assertEqual(code, 202)
        self.assertEqual(saved, {'cookie': 'tok', 'csrf': 'csrf1'})
        login = [x for x in calls if x[1] == '/auth/test/login'][0]
        self.assertEqual((login[3], login[4]), (url, {'principalId': 'op-1'}))
        sync = [x for x in calls if x[1] == '/api/v1/sync/sphere'][0]
        self.assertEqual(sync[2], 'csrf1')


class QuotaRetry(unittest.TestCase):
    now = c.ts('2026-10-16T04:00:00Z')

    def run_(self, status, ended, reason='agent_error.provider_quota_limit', error=''):
        return {'status': status, 'created_at': ended, 'completed_at': ended, 'failure_reason': reason, 'error': error}

    def test_лимит_20_минут_назад_повторяется(self):
        self.assertTrue(c.quota_retry_due([self.run_('failed', '2026-10-16T03:30:00Z')], self.now, None, 20))

    def test_лимит_только_что_ждём(self):
        self.assertFalse(c.quota_retry_due([self.run_('failed', '2026-10-16T03:50:00Z')], self.now, None, 20))

    def test_есть_активный_ран_не_трогаем(self):
        runs = [self.run_('failed', '2026-10-16T03:00:00Z'), {'status': 'running', 'created_at': '2026-10-16T03:10:00Z'}]
        self.assertFalse(c.quota_retry_due(runs, self.now, None, 20))

    def test_обычная_ошибка_не_повторяется(self):
        self.assertFalse(c.quota_retry_due([self.run_('failed', '2026-10-16T03:00:00Z', 'agent_error.crash', 'boom')], self.now, None, 20))

    def test_лимит_по_тексту_ошибки(self):
        self.assertTrue(c.quota_retry_due([self.run_('failed', '2026-10-16T03:00:00Z', '', 'You’ve hit your usage limit')], self.now, None, 20))

    def test_недавний_повтор_не_повторяется(self):
        self.assertFalse(c.quota_retry_due([self.run_('failed', '2026-10-16T03:00:00Z')], self.now, '2026-10-16T03:50:00+00:00', 20))

    def test_последний_ран_успешный(self):
        runs = [self.run_('failed', '2026-10-16T03:00:00Z'), {'status': 'completed', 'created_at': '2026-10-16T03:10:00Z'}]
        self.assertFalse(c.quota_retry_due(runs, self.now, None, 20))


O = [{'issue': 'F', 'agent_id': 'be', 'thinking_level': 'xhigh', 'restore': 'high'}]


class Overrides(unittest.TestCase):
    def st(self, *issues): return [{'stage': 1, 'issues': list(issues)}]

    def test_назначаемая_сейчас_задача_поднимает_уровень_до_рана(self):
        self.assertEqual(c.override_levels(self.st(issue('F')), O, {'F'}, {'be': 'high'}), [('be', 'xhigh')])

    def test_задача_в_работе_держит_уровень(self):
        self.assertEqual(c.override_levels(self.st(issue('F', 'in_progress', 'sq')), O, set(), {'be': 'xhigh'}), [])

    def test_неназначенная_задача_уровень_не_трогает(self):
        self.assertEqual(c.override_levels(self.st(issue('F')), O, set(), {'be': 'high'}), [])

    def test_закрытая_задача_возвращает_уровень(self):
        self.assertEqual(c.override_levels(self.st(issue('F', 'done', 'sq')), O, set(), {'be': 'xhigh'}), [('be', 'high')])

    def test_ручную_правку_после_закрытия_не_перетирает(self):
        self.assertEqual(c.override_levels(self.st(issue('F', 'done', 'sq')), O, set(), {'be': 'medium'}), [])


if __name__ == '__main__':
    unittest.main()
