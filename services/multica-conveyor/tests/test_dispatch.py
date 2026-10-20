"""Назначение задачи скваду: без реальной Multica, состояние — во временном каталоге."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_conveyor import c


NOW = dt.datetime(2026, 10, 19, 12, tzinfo=dt.timezone.utc)
EPIC = {'key': 'EPIC-1', 'workspace': 'ws', 'squad_id': 'squad'}


class LostResponse(Exception):
    """Запись дошла или не дошла до сервера, ответа нет."""


class FakeMultica:
    """Сервер в памяти: каждая запись в задачу поднимает её ревизию, как настоящий."""

    def __init__(self, *issues):
        self.issues = {i['identifier']: {'revision': 1, 'assignee_id': None, 'description': '', **i} for i in issues}
        self.runs = {}
        self.writes = []
        self.fail = None        # 'before' — запись не дошла, 'after' — дошла, ответ потерян
        self.stale = False      # чтение отдаёт снимок до последней записи
        self.server_squad = None  # стадии эпика назначает сервер multica (`issue stages`)
        self.stages_missing = False  # старый multica без `issue stages`

    def __call__(self, *args, write=False):
        if write:
            self.writes.append(args)
            if self.fail == 'before':
                raise LostResponse(args)
            self.snapshot = copy.deepcopy(self.issues)
            issue = self.issues[args[2]]
            if args[:2] == ('issue', 'update'):
                issue['status'] = args[args.index('--status') + 1]
            elif args[:2] == ('issue', 'assign'):
                issue['assignee_id'] = args[args.index('--to-id') + 1]
                issue['status'] = 'todo' if issue['status'] == 'backlog' else issue['status']
                self.runs.setdefault(args[2], []).append({'status': 'queued', 'created_at': NOW.isoformat()})
            else:
                raise AssertionError(f'непредусмотренная запись: {args}')
            issue['revision'] += 1
            if self.fail == 'after':
                raise LostResponse(args)
            return {}
        issues = self.snapshot if self.stale else self.issues
        if args[:2] == ('issue', 'children'):
            return {'stages': [{'stage': 1, 'issues': copy.deepcopy(list(issues.values()))}], 'unstaged': []}
        if args[:2] == ('issue', 'get'):
            return copy.deepcopy(issues[args[2]])
        if args[:2] == ('issue', 'stages'):
            if self.stages_missing:
                raise RuntimeError('multica issue stages: unknown command "stages"')
            return {'issue_id': args[2], 'squad_id': self.server_squad}
        if args[:2] == ('issue', 'runs'):
            return copy.deepcopy(self.runs.get(args[2], []))
        raise AssertionError(f'непредусмотренное чтение: {args}')

    def assigns(self, key=None):
        return [a for a in self.writes if a[:2] == ('issue', 'assign') and (key is None or a[2] == key)]


class Dispatch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.controls = self.root / 'controls.json'
        self.controls.write_text('{}')
        self.state = self.root / 'state.json'

    def tick(self, api, at=NOW, dry=False):
        """Один тик как после рестарта: состояние читается с диска и пишется обратно."""
        with patch.dict(os.environ, {'MULTICA_CONTROL_STATE': str(self.controls)}), \
                patch.object(c, 'STATE', self.state), patch.object(c, 'Multica', return_value=api), \
                patch.object(c, 'now_utc', return_value=at):
            w = c.Watch(dry)
            w.target_key = EPIC['key']
            try:
                c.run_epic(EPIC, w, {'epics': []})
            except LostResponse:
                pass
            finally:
                w.save()

    def journal(self):
        return json.loads(self.state.read_text()).get('_dispatch', {}) if self.state.exists() else {}

    def test_стадии_назначает_сервер_сторож_не_назначает(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'backlog'})
        api.server_squad = 'squad'
        self.tick(api)
        self.assertEqual(api.assigns(), [])

    def test_старый_multica_без_issue_stages_назначает_сторож(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'backlog'})
        api.stages_missing = True
        self.tick(api)
        self.assertEqual(len(api.assigns('PKG-1')), 1)

    def test_повтор_тика_и_рестарт_не_назначают_второй_раз(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'backlog'})
        self.tick(api)
        self.tick(api)
        self.tick(api, NOW + dt.timedelta(hours=1))
        self.assertEqual(len(api.assigns('PKG-1')), 1)
        self.assertEqual(self.journal(), {}, 'подтверждённое назначение снимает намерение')

    def test_ответ_потерян_после_записи_второго_назначения_нет(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'todo'})
        api.fail = 'after'
        self.tick(api)
        api.fail = None
        self.tick(api)
        self.assertEqual(len(api.assigns('PKG-1')), 1)

    def test_запись_не_дошла_повтор_только_после_паузы(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'todo'})
        api.fail = 'before'
        self.tick(api)
        api.fail = None
        self.tick(api, NOW + dt.timedelta(minutes=2))
        self.assertEqual(len(api.assigns('PKG-1')), 1, 'исход неизвестен, ревизия та же — ждём')
        self.tick(api, NOW + dt.timedelta(minutes=c.DISPATCH_SETTLE_MINUTES + 1))
        self.assertEqual(len(api.assigns('PKG-1')), 2)
        self.assertEqual(api.issues['PKG-1']['assignee_id'], 'squad')

    def test_устаревшее_чтение_не_даёт_второго_назначения(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'todo'})
        self.tick(api)
        api.stale = True
        self.tick(api, NOW + dt.timedelta(minutes=2))
        self.assertEqual(len(api.assigns('PKG-1')), 1)

    def test_законно_возвращённая_в_todo_назначается_снова(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'backlog'})
        self.tick(api)
        api.runs['PKG-1'] = [{'status': 'completed'}]
        api.issues['PKG-1'].update(assignee_id=None, status='todo', revision=api.issues['PKG-1']['revision'] + 1)
        self.tick(api, NOW + dt.timedelta(minutes=2))
        self.assertEqual(len(api.assigns('PKG-1')), 2)

    def test_активный_ран_задачи_блокирует_назначение(self):
        for st in ('queued', 'dispatched', 'running', 'pending', 'preparing', 'waiting_local_directory'):
            with self.subTest(status=st):
                self.state.unlink(missing_ok=True)
                api = FakeMultica({'identifier': 'PKG-1', 'status': 'todo'})
                api.runs['PKG-1'] = [{'status': st}]
                self.tick(api)
                self.assertEqual(api.writes, [])

    def test_раны_и_будильники_других_задач_не_блокируют(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'todo'},
                          {'identifier': 'PKG-2', 'status': 'in_progress', 'assignee_id': 'squad'})
        api.runs['PKG-2'] = [{'status': 'running'}]
        self.tick(api)
        self.assertEqual(len(api.assigns('PKG-1')), 1)

    def test_назначенная_во_время_тика_не_назначается(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'todo'})
        children = api('issue', 'children', 'EPIC-1')
        api.issues['PKG-1'].update(assignee_id='lead', revision=2)
        real = api.__call__

        def call(*args, write=False):
            # Список детей прочитан до того, как лидер назначил задачу сам.
            return children if args[:2] == ('issue', 'children') else real(*args, write=write)
        self.tick(call)
        self.assertEqual(api.writes, [])

    def test_ждущая_заказчика_на_свежем_чтении_не_назначается(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'todo'})
        children = api('issue', 'children', 'EPIC-1')
        api.issues['PKG-1']['description'] = c.HOLD + ' ответа по доступу'
        real = api.__call__
        self.tick(lambda *a, write=False: children if a[:2] == ('issue', 'children') else real(*a, write=write))
        self.assertEqual(api.writes, [])

    def test_холостой_прогон_не_пишет_и_не_журналирует(self):
        api = FakeMultica({'identifier': 'PKG-1', 'status': 'backlog'})
        self.tick(api, dry=True)
        self.assertEqual(api.writes, [])
        self.assertFalse(self.state.exists())

    def test_активные_статусы_ранов(self):
        self.assertTrue({'preparing', 'waiting_local_directory'} <= c.ACTIVE_RUN)


if __name__ == '__main__':
    unittest.main()
