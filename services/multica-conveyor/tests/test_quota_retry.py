"""Повтор после лимита: один владелец — полоса провайдеров, повтор привязан к необработанному поручению."""
import copy
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_conveyor import c

NOW = c.now_utc().replace(microsecond=0)
AGENT, OTHER, LEAD = 'agent-a', 'agent-b', 'lead'


def at(minutes):
    return (NOW + dt.timedelta(minutes=minutes)).isoformat()


def failed(rid='failed', agent=AGENT, minutes=-5, **extra):
    return {'id': rid, 'agent_id': agent, 'issue_id': 'i', 'runtime_id': 'claude', 'status': 'failed',
            'error': 'You’ve hit your usage limit', 'created_at': at(minutes), **extra}


def done(rid, agent=AGENT, minutes=-1, **extra):
    return {'id': rid, 'agent_id': agent, 'issue_id': 'i', 'status': 'completed', 'created_at': at(minutes), **extra}


def issue(status='in_progress', assignee=AGENT, kind='agent'):
    return {'identifier': 'ISS-1', 'status': status, 'assignee_id': assignee, 'assignee_type': kind}


class Plan(unittest.TestCase):
    def test_новое_поручение_в_задаче_на_сдаче_после_успешного_отчёта(self):
        runs = [done('report', minutes=-30), failed(kind='comment', trigger_comment_id='c2')]
        self.assertEqual(c.quota_retry_plan(runs[1], runs, issue('in_review')), ('wakeup', ''))

    def test_упоминание_в_задаче_другого_исполнителя(self):
        runs = [failed(kind='comment', trigger_comment_id='c1')]
        self.assertEqual(c.quota_retry_plan(runs[0], runs, issue(assignee=OTHER)), ('wakeup', ''))

    def test_упоминание_в_задаче_сквада_не_лидера(self):
        runs = [failed(kind='comment', trigger_comment_id='c1')]
        self.assertEqual(c.quota_retry_plan(runs[0], runs, issue(assignee='squad', kind='squad'), LEAD)[0], 'wakeup')

    def test_поручение_исполнителя_и_лидера_через_rerun(self):
        run = failed()
        self.assertEqual(c.quota_retry_plan(run, [run], issue())[0], 'rerun')
        lead = failed(agent=LEAD)
        self.assertEqual(c.quota_retry_plan(lead, [lead], issue(assignee='squad', kind='squad'), LEAD)[0], 'rerun')
        # Лидер неизвестен — ран лидера узнаётся по is_leader_task.
        flagged = failed(agent=LEAD, is_leader_task=True)
        self.assertEqual(c.quota_retry_plan(flagged, [flagged], issue(assignee='squad', kind='squad'))[0], 'rerun')

    def test_активный_или_ожидающий_ран_ждём(self):
        for st in ('queued', 'running', 'dispatched', 'pending', 'preparing'):
            with self.subTest(status=st):
                runs = [failed(), {'id': 'x', 'agent_id': OTHER, 'status': st, 'created_at': at(-1)}]
                self.assertEqual(c.quota_retry_plan(runs[0], runs, issue())[0], 'wait')

    def test_более_поздний_ран_агента_снимает_повтор(self):
        for later in (done('ok'), failed('again', minutes=-1), {**done('x'), 'status': 'cancelled'}):
            with self.subTest(later=later['id']):
                runs = [failed(), later]
                self.assertEqual(c.quota_retry_plan(runs[0], runs, issue())[0], 'drop')

    def test_поручение_уже_обработал_другой_ран(self):
        run = failed(kind='comment', trigger_comment_id='c1')
        for other in (done('o', agent=OTHER, trigger_comment_id='c1'), done('o', agent=OTHER, delivered_comment_ids=['c1'])):
            with self.subTest(other=other):
                self.assertEqual(c.quota_retry_plan(run, [run, other], issue('in_review'))[0], 'drop')
        wake = failed(wakeup_id='w1')
        self.assertEqual(c.quota_retry_plan(wake, [wake, done('o', agent=OTHER, wakeup_id='w1')], issue())[0], 'drop')
        # Более ранний ран с тем же комментарием — не обработка этого поручения.
        early = done('early', agent=OTHER, minutes=-30, trigger_comment_id='c1')
        self.assertEqual(c.quota_retry_plan(run, [early, run], issue('in_review'))[0], 'wakeup')

    def test_закрытая_задача(self):
        for st in ('done', 'cancelled'):
            with self.subTest(status=st):
                self.assertEqual(c.quota_retry_plan(failed(), [failed()], issue(st))[0], 'drop')


class Lane(unittest.TestCase):
    """Полоса провайдеров целиком: учёт падений, ворота доступности профиля, ровно один повтор."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / 'state.json'
        (self.root / 'controls.json').write_text('{}')
        for p in (patch.object(c, 'STATE', self.state),
                  patch.dict(os.environ, {'MULTICA_CONTROL_STATE': str(self.root / 'controls.json')}),
                  patch.object(c, 'Multica', return_value=self.api), patch.object(c, 'quotas', return_value=[]),
                  patch.object(c.control, 'runtime_names', return_value={'codex': 'Codex', 'claude': 'Claude'}),
                  patch.object(c.control, 'availability', side_effect=lambda *a: dict(self.avail)),
                  patch.object(c.control, 'quota_rows', return_value=[]),
                  patch.object(c.control, 'reset_at', return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        self.cfg = {'providers': {'workspace': 'ws', 'agents': {
            AGENT: {'name': 'Бэкенд', 'chain': [{'runtime_id': 'codex', 'model': 'gpt'},
                                                {'runtime_id': 'claude', 'model': 'sonnet'}]}}},
            'status_dir': str(self.root / 'status')}
        self.actual = {'runtime_id': 'claude', 'model': 'sonnet'}
        self.avail = {'codex': True, 'claude': False}
        self.runs = [failed(kind='comment', trigger_comment_id='c1')]
        self.issue = issue(assignee=OTHER)
        self.writes = []

    def api(self, *args, **kwargs):
        if kwargs.get('write'):
            self.writes.append(args)
        if args[:2] == ('agent', 'get'):
            return copy.deepcopy(self.actual)
        if args[:2] == ('agent', 'tasks'):
            return copy.deepcopy(self.runs)
        if args[:2] == ('issue', 'runs'):
            return copy.deepcopy([r for r in self.runs if r.get('issue_id') == args[2]])
        if args[:2] == ('agent', 'update'):
            self.actual.update(runtime_id=args[args.index('--runtime-id') + 1], model=args[args.index('--model') + 1])
        if args[:2] == ('issue', 'get'):
            return copy.deepcopy(self.issue)
        if args[:2] == ('squad', 'get'):
            return {'leader_id': LEAD}
        if args[:3] == ('issue', 'wakeup', 'create'):
            return {'id': 'wake-1'}
        return {}

    def tick(self):
        c.run(self.cfg, False, providers_only=True)

    def retries(self):
        return [w for w in self.writes if w[:2] == ('issue', 'rerun') or w[:3] == ('issue', 'wakeup', 'create')]

    def test_лимит_создаёт_ровно_один_повтор_по_упоминанию(self):
        for _ in range(3):
            self.tick()
        self.assertEqual(self.actual['runtime_id'], 'codex')
        self.assertEqual(len(self.retries()), 1)
        wake = self.retries()[0]
        self.assertEqual(wake[wake.index('--agent-id') + 1], AGENT)
        self.assertEqual(wake[wake.index('--parent') + 1], 'c1')
        self.assertIn('c1', wake[wake.index('--instruction') + 1])
        pending = json.loads(self.state.read_text())['_providers'][AGENT]['quota_pending']['failed']
        self.assertEqual((pending['how'], pending['wakeup']), ('wakeup', 'wake-1'))

    def test_новое_поручение_в_задаче_на_сдаче_повторяется_будильником(self):
        self.issue = issue('in_review')
        self.runs = [done('report', minutes=-30), failed(kind='comment', trigger_comment_id='c2')]
        self.tick()
        self.assertEqual([w[:3] for w in self.retries()], [('issue', 'wakeup', 'create')])

    def test_своя_задача_в_работе_через_rerun(self):
        self.issue = issue()
        self.tick()
        self.tick()
        self.assertEqual(self.retries(), [('issue', 'rerun', 'i')])

    def test_возврат_на_доступный_основной_профиль_повторяет_отложенное(self):
        # Падение учтено раньше, но тогда по задаче шёл чужой ран; агент работает на запасном.
        self.runs = [failed(runtime_id='codex', minutes=-50), done('later-other', agent=OTHER, minutes=-40),
                     {**done('own-other-issue', minutes=-35), 'issue_id': 'other', 'runtime_id': 'claude'}]
        self.issue = issue(assignee=OTHER)
        self.state.write_text(json.dumps({'_providers': {AGENT: {
            'idx': 1, 'since': at(-45), 'quota_since': at(-60), 'failure_seen': 'failed',
            'quota_pending': {'failed': {'issue': 'i', 'at': at(-50)}}}}}))
        self.avail = {'codex': True, 'claude': True}
        self.tick()
        state = json.loads(self.state.read_text())
        self.assertEqual(state['_providers'][AGENT]['idx'], 0)
        self.assertTrue(any('возвращается на' in e['text'] for e in state['_events']))
        self.assertEqual([w[:3] for w in self.retries()], [('issue', 'wakeup', 'create')])

    def test_нет_повтора_пока_профиль_остывает_или_вся_цепочка_ждёт(self):
        self.avail = {'codex': False, 'claude': False}
        self.tick()
        self.tick()
        self.assertEqual(self.retries(), [])
        self.assertTrue(json.loads(self.state.read_text())['_providers'][AGENT].get('waiting'))

    def test_ручной_режим_не_повторяет(self):
        (self.root / 'controls.json').write_text(json.dumps({'agents': {AGENT: {'mode': 'manual'}}}))
        self.avail = {'codex': True, 'claude': True}
        self.tick()
        self.assertEqual(self.retries(), [])

    def test_нет_повтора_при_активном_позднем_успешном_и_обработанном(self):
        cases = {
            'активный': [failed(), {'id': 'q', 'agent_id': OTHER, 'issue_id': 'i', 'status': 'queued', 'created_at': at(-1)}],
            'поздний успешный': [failed(), done('ok')],
            'обработано': [failed(kind='comment', trigger_comment_id='c1'), done('o', agent=OTHER, trigger_comment_id='c1')],
        }
        for name, runs in cases.items():
            with self.subTest(name):
                self.writes.clear()
                self.state.unlink(missing_ok=True)
                self.actual = {'runtime_id': 'claude', 'model': 'sonnet'}
                self.runs = runs
                self.tick()
                self.assertEqual(self.retries(), [])

    def test_закрытая_задача_не_повторяется(self):
        self.issue = issue('done')
        self.tick()
        self.assertEqual(self.retries(), [])
        self.assertEqual(json.loads(self.state.read_text())['_providers'][AGENT]['quota_pending']['failed']['how'], 'drop')

    def test_падения_до_включения_учёта_не_повторяются(self):
        self.runs = [failed(minutes=-30)]
        self.tick()
        self.assertEqual(self.retries(), [])

    def test_сбой_multica_оставляет_ран_в_учёте(self):
        broken = {'n': 0}
        api = self.api

        def flaky(*args, **kwargs):
            if args[:3] == ('issue', 'wakeup', 'create') and not broken['n']:
                broken['n'] += 1
                raise RuntimeError('multica issue wakeup: 502')
            return api(*args, **kwargs)
        with patch.object(c, 'Multica', return_value=flaky):
            self.tick()
            self.tick()
        self.assertEqual(broken['n'], 1)  # первая попытка упала, ран остался в учёте
        self.assertEqual(len(self.retries()), 1)
        self.assertEqual(json.loads(self.state.read_text())['_providers'][AGENT]['quota_pending']['failed']['how'], 'wakeup')


class EpicLaneHasNoQuotaRetry(unittest.TestCase):
    def test_полоса_эпиков_не_повторяет_после_лимита(self):
        writes = []
        task = {'identifier': 'ISS-2', 'assignee_id': AGENT, 'status': 'in_progress'}

        def api(*args, **kwargs):
            if kwargs.get('write'):
                writes.append(args)
            if args[:2] == ('issue', 'children'):
                return {'stages': [{'stage': 1, 'issues': [task]}]}
            if args[:2] == ('issue', 'runs'):
                return [failed(minutes=-120, completed_at=at(-119))]
            return {}
        with tempfile.TemporaryDirectory() as tmp, patch.object(c, 'STATE', Path(tmp) / 'state.json'), \
                patch.dict(os.environ, {'MULTICA_CONTROL_STATE': str(Path(tmp) / 'controls.json')}), \
                patch.object(c, 'Multica', return_value=api):
            w = c.Watch(False)
            c.run_epic({'key': 'ISS-1', 'workspace': 'ws', 'quota_retry_minutes': 20}, w, {'epics': []})
        self.assertEqual(writes, [])
        self.assertNotIn('_quota_retry', w.state)


if __name__ == '__main__':
    unittest.main()
