import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_conveyor import c


class ProviderLane(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state.json'
        self.controls = self.root / 'controls.json'
        self.controls.write_text('{}')
        p = patch.object(c, 'STATE', self.state)
        p.start()
        self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'MULTICA_CONTROL_STATE': str(self.controls)})
        p.start()
        self.addCleanup(p.stop)
        self.cfg = {'epics': [{'key': 'TEST-1', 'workspace': 'ws'}],
                    'status_dir': str(self.root / 'status')}

    def test_provider_switch_and_single_retry_while_acceptance_is_blocked(self):
        started, release = threading.Event(), threading.Event()
        failures = []
        now = c.now_utc()
        failed = {'id': 'failed', 'agent_id': 'a', 'issue_id': 'i', 'runtime_id': 'claude',
                  'status': 'failed', 'error': 'session limit: hit your session limit',
                  'created_at': (now - dt.timedelta(minutes=1)).isoformat()}
        runs = [failed]
        actual = {'runtime_id': 'claude', 'model': 'sonnet'}
        writes = []
        self.cfg['providers'] = {'workspace': 'ws', 'agents': {
            'a': {'name': 'Backend', 'chain': [{'runtime_id': 'codex', 'model': 'gpt'},
                                             {'runtime_id': 'claude', 'model': 'sonnet'}]}}}

        def api(*args, **kwargs):
            if kwargs.get('write'):
                writes.append(args)
            if args[:2] == ('agent', 'get'):
                return copy.deepcopy(actual)
            if args[:2] == ('agent', 'tasks') or args[:2] == ('issue', 'runs'):
                return copy.deepcopy(runs)
            if args[:2] == ('agent', 'update'):
                actual.update(runtime_id=args[args.index('--runtime-id') + 1],
                              model=args[args.index('--model') + 1])
            if args[:2] == ('issue', 'get'):
                return {'assignee_type': 'agent', 'assignee_id': 'a', 'status': 'in_progress'}
            if args[:2] == ('issue', 'rerun'):
                runs.append({'id': 'retry', 'agent_id': 'a', 'issue_id': 'i', 'runtime_id': 'codex',
                             'status': 'queued', 'created_at': (now + dt.timedelta(seconds=1)).isoformat()})
            return {}

        def blocked(epic, watch, snapshot, **kwargs):
            started.set()
            if not release.wait(10):
                raise AssertionError('acceptance barrier timed out')
            watch.state['accepted'] = True
            watch.log('merge', 'acceptance finished')

        def accept():
            try:
                c.run(self.cfg, False)
            except BaseException as e:
                failures.append(e)

        with patch.object(c, 'run_epic', side_effect=blocked), patch.object(c, 'run_stands'), \
                patch.object(c, 'Multica', return_value=api), patch.object(c, 'quotas', return_value=[]), \
                patch.object(c.control, 'runtime_names', return_value={'codex': 'Codex', 'claude': 'Claude'}), \
                patch.object(c.control, 'availability', return_value={'codex': True, 'claude': False}), \
                patch.object(c.control, 'quota_rows', return_value=[]), \
                patch.object(c.control, 'reset_at', return_value=now + dt.timedelta(hours=1)):
            thread = threading.Thread(target=accept)
            thread.start()
            try:
                self.assertTrue(started.wait(3))
                c.run(self.cfg, False, providers_only=True)
                c.run(self.cfg, False, providers_only=True)
                self.assertTrue(thread.is_alive(), 'provider pass must finish before acceptance')
                self.assertEqual(actual['runtime_id'], 'codex')
                self.assertEqual(sum(a[:2] == ('issue', 'rerun') for a in writes), 1)
                self.assertEqual(json.loads(self.state.read_text())['_providers']['a']['idx'], 0)
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        state = json.loads(self.state.read_text())
        self.assertTrue(state['accepted'])
        self.assertEqual(state['_providers']['a']['idx'], 0)
        self.assertTrue(any(e['kind'] == 'provider' for e in state['_events']))
        self.assertTrue(any(e['kind'] == 'merge' for e in state['_events']))
        snapshot = json.loads((self.root / 'status/status.json').read_text())
        self.assertEqual(snapshot['agents'][0]['runtime'], 'Codex')

    def test_stale_acceptance_save_preserves_provider_state_and_both_events(self):
        self.state.write_text(json.dumps({'_providers': {'a': {'idx': 1}}, 'old': True}))
        acceptance = c.Watch(False)
        provider = c.Watch(False)
        provider.state['_providers']['a']['idx'] = 0
        provider.log('provider', 'switched')
        provider.save()
        acceptance.state['accepted'] = True
        acceptance.log('merge', 'accepted')
        acceptance.save()
        result = json.loads(self.state.read_text())
        self.assertEqual(result['_providers']['a']['idx'], 0)
        self.assertEqual([e['text'] for e in result['_events']], ['switched', 'accepted'])
        acceptance.save()
        self.assertEqual(len(json.loads(self.state.read_text())['_events']), 2)

    def test_corrupt_state_stops_actions(self):
        self.state.write_text('{broken')
        with patch.object(c, 'run_providers') as providers:
            with self.assertRaises(ValueError):
                c.run(self.cfg, False, providers_only=True)
            providers.assert_not_called()

    def test_provider_lane_never_runs_acceptance_or_stands(self):
        with patch.object(c, 'run_epic') as epics, patch.object(c, 'run_stands') as stands, \
                patch.object(c, 'run_providers') as providers, patch.object(c, 'quotas', return_value=[]):
            c.run(self.cfg, False, providers_only=True)
            epics.assert_not_called()
            stands.assert_not_called()
            providers.assert_called_once()

    def test_default_lane_never_runs_providers(self):
        with patch.object(c, 'run_epic'), patch.object(c, 'run_stands'), \
                patch.object(c, 'run_providers') as providers, patch.object(c, 'quotas', return_value=[]):
            c.run(self.cfg, False)
            providers.assert_not_called()

    def test_duplicate_provider_pass_is_skipped(self):
        with c.lane_lock(True) as acquired, patch.object(c, 'run_providers') as providers:
            self.assertTrue(acquired)
            c.run(self.cfg, False, providers_only=True)
            providers.assert_not_called()

    def test_publisher_preserves_epics_and_uses_fresh_provider_snapshot(self):
        self.state.write_text('{}')
        snapshot = {'tick': 'old', 'epics': [{'key': 'TEST-1', 'name': 'Test', 'stage': None, 'stages': []}],
                    'agents': [], 'errors': [], 'stands': [], 'quotas': []}
        c.write_status(self.cfg, snapshot, [])
        provider = {'tick': 'new', 'agents': [], 'errors': ['provider error']}
        self.state.with_name('providers-status.json').write_text(json.dumps(provider))
        c.write_status(self.cfg, {'epics': []}, [], providers_only=True)
        result = json.loads((self.root / 'status/status.json').read_text())
        self.assertEqual(result['epics'][0]['key'], 'TEST-1')
        self.assertEqual(result['provider_tick'], 'new')
        self.assertEqual(result['provider_errors'], ['provider error'])
        c.write_status(self.cfg, snapshot, [])
        result = json.loads((self.root / 'status/status.json').read_text())
        self.assertEqual(result['provider_tick'], 'new')

    def test_retry_rechecks_runs_after_taking_shared_lock(self):
        failed = {'id': 'failed', 'status': 'failed', 'error': 'usage limit',
                  'created_at': '2026-01-01T00:00:00Z'}
        issue = {'identifier': 'TEST-2', 'assignee_id': 'a', 'status': 'in_progress'}
        reads = 0
        writes = []

        def api(*args, **kwargs):
            nonlocal reads
            if kwargs.get('write'):
                writes.append(args)
            if args[:2] == ('issue', 'children'):
                return {'stages': [{'stage': 1, 'issues': [issue]}]}
            if args[:2] == ('issue', 'get'):
                return issue
            if args[:2] == ('issue', 'runs'):
                reads += 1
                return [failed] if reads == 1 else [{'status': 'queued'}]
            return {}

        watch = c.Watch(False)
        with patch.object(c, 'Multica', return_value=api):
            c.run_epic(self.cfg['epics'][0], watch, {'epics': []})
        self.assertEqual(reads, 2)
        self.assertEqual(writes, [])

    def test_leader_wakeup_run_on_squad_issue_is_rerun_after_switch(self):
        now = c.now_utc()
        failed = {'id': 'failed', 'agent_id': 'a', 'issue_id': 'i', 'runtime_id': 'claude', 'status': 'failed', 'is_leader_task': None,
                  'error': 'usage limit: подписки runtime выше лимита агентам',
                  'created_at': (now - dt.timedelta(minutes=1)).isoformat()}
        writes = []
        self.cfg['providers'] = {'workspace': 'ws', 'agents': {
            'a': {'name': 'Lead', 'chain': [{'runtime_id': 'codex', 'model': 'gpt'},
                                          {'runtime_id': 'claude', 'model': 'sonnet'}]}}}
        actual = {'runtime_id': 'claude', 'model': 'sonnet'}

        def api(*args, **kwargs):
            if kwargs.get('write'):
                writes.append(args)
            if args[:2] == ('agent', 'get'):
                return copy.deepcopy(actual)
            if args[:2] in (('agent', 'tasks'), ('issue', 'runs')):
                return [failed]
            if args[:2] == ('issue', 'get'):
                return {'assignee_type': 'squad', 'assignee_id': 'squad-1', 'status': 'in_progress'}
            return {}

        with patch.object(c, 'run_stands'), patch.object(c, 'Multica', return_value=api), \
                patch.object(c, 'quotas', return_value=[]), \
                patch.object(c.control, 'runtime_names', return_value={'codex': 'Codex', 'claude': 'Claude'}), \
                patch.object(c.control, 'availability', return_value={'codex': True, 'claude': False}), \
                patch.object(c.control, 'quota_rows', return_value=[]), \
                patch.object(c.control, 'reset_at', return_value=now + dt.timedelta(hours=1)):
            c.run(self.cfg, False, providers_only=True)
        self.assertIn(('issue', 'rerun', 'i'), [w[:3] for w in writes])

if __name__ == '__main__':
    unittest.main()
