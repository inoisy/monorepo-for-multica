import copy
import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_conveyor import c


NOW = dt.datetime(2026, 10, 18, 10, tzinfo=dt.timezone.utc)


def failed(error='require-vless: initialize failed', age=30, **extra):
    return {'id': 'failed', 'status': 'failed', 'error': error,
            'created_at': (NOW - dt.timedelta(minutes=age + 1)).isoformat(),
            'completed_at': (NOW - dt.timedelta(minutes=age)).isoformat(), **extra}


class InfraDecision(unittest.TestCase):
    def test_infra_signatures_and_runtime_recovery(self):
        for error in ('require-vless', 'initialize failed', 'handshake timeout', 'daemon restarted',
                      'routing discovery failed', 'control protocol failed', 'process exited', 'timed out',
                      'ETIMEDOUT', 'ECONNRESET', 'ECONNREFUSED', 'connection reset', 'connection refused'):
            with self.subTest(error=error):
                self.assertTrue(c.is_infra_failure(failed(error.upper())))
        self.assertTrue(c.is_infra_failure(failed('', failure_reason='runtime_recovery')))

    def test_quota_business_error_and_success_are_not_infra(self):
        for run in (failed('usage limit: process exited'), failed('assertion failed'),
                    failed('require-vless', status='done'), failed('process exited', failure_reason='provider_quota_limit')):
            with self.subTest(run=run):
                self.assertFalse(c.is_infra_failure(run))

    def test_retry_waits_for_completion_and_previous_retry(self):
        self.assertEqual(c.infra_retry([failed()], NOW, {}, 20, 3), 'retry')
        self.assertIsNone(c.infra_retry([failed(age=19)], NOW, {}, 20, 3))
        self.assertIsNone(c.infra_retry([failed()], NOW, {'at': (NOW - dt.timedelta(minutes=19)).isoformat()}, 20, 3))
        self.assertEqual(c.infra_retry([failed()], NOW, {'at': (NOW - dt.timedelta(minutes=20)).isoformat()}, 20, 3), 'retry')

    def test_active_or_newer_noninfra_run_prevents_retry(self):
        for status in c.ACTIVE_RUN:
            with self.subTest(status=status):
                self.assertIsNone(c.infra_retry([failed(), {'status': status}], NOW, {}, 20, 3))
        self.assertIsNone(c.infra_retry([], NOW, {}, 20, 3))
        self.assertIsNone(c.infra_retry([failed(), failed('assertion failed', age=25)], NOW, {}, 20, 3))

    def test_infra_retry_limit(self):
        self.assertEqual(c.infra_retry([failed()], NOW, {'n': 2}, 20, 3), 'retry')
        self.assertEqual(c.infra_retry([failed()], NOW, {'n': 3}, 20, 3), 'give_up')
        self.assertEqual(c.infra_retry([failed()], NOW, {}, 20, 0), 'give_up')


class InfraEpic(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.controls = self.root / 'controls.json'
        self.controls.write_text('{}')
        p = patch.object(c, 'STATE', self.root / 'state.json')
        p.start()
        self.addCleanup(p.stop)
        self.watch = c.Watch(True)
        self.watch.state = {}
        self.watch.dry = False
        self.epic = {'key': 'TEST-1', 'workspace': 'ws'}
        self.issue = {'identifier': 'TEST-2', 'assignee_id': 'agent', 'status': 'in_progress'}
        self.runs = [failed()]
        self.fresh_runs = None
        self.writes = []
        self.reads = 0
        self.patches = [patch.dict(os.environ, {'MULTICA_CONTROL_STATE': str(self.controls)}),
                        patch.object(c, 'now_utc', return_value=NOW),
                        patch.object(c, 'Multica', return_value=self.api)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def api(self, *args, **kwargs):
        if kwargs.get('write') and not self.watch.dry:
            self.writes.append(args)
        if args[:2] == ('issue', 'children'):
            return {'stages': [{'stage': 1, 'issues': [copy.deepcopy(self.issue)]}]}
        if args[:2] == ('issue', 'get'):
            return copy.deepcopy(self.issue)
        if args[:2] == ('issue', 'runs'):
            self.reads += 1
            return copy.deepcopy(self.fresh_runs if self.reads % 2 == 0 and self.fresh_runs is not None else self.runs)
        return {}

    def run_epic(self, **kwargs):
        c.run_epic(self.epic, self.watch, {'epics': []}, **kwargs)

    def test_retry_is_counted_and_not_repeated_before_interval(self):
        self.run_epic()
        self.assertEqual(self.writes, [('issue', 'rerun', 'TEST-2')])
        self.assertEqual(self.watch.state['_infra_retry']['TEST-2'], {'at': NOW.isoformat(), 'n': 1})
        self.run_epic()
        self.assertEqual(len(self.writes), 1)

    def test_infra_retry_limit_logs_once_and_noninfra_resets_counter(self):
        self.watch.state['_infra_retry'] = {'TEST-2': {'n': 3}}
        self.run_epic()
        self.run_epic()
        self.assertEqual(self.writes, [])
        self.assertEqual(len([e for e in self.watch.state['_events'] if e['kind'] == 'fail']), 1)
        self.assertTrue(self.watch.state['_infra_retry']['TEST-2']['gave_up'])
        self.runs = [failed('assertion failed')]
        self.run_epic()
        self.assertNotIn('TEST-2', self.watch.state['_infra_retry'])

    def test_queued_retry_keeps_consecutive_failure_count(self):
        self.watch.state['_infra_retry'] = {'TEST-2': {'n': 2}}
        self.runs = [failed(), {'id': 'retry', 'status': 'queued', 'created_at': NOW.isoformat()}]
        self.run_epic()
        self.assertEqual(self.watch.state['_infra_retry']['TEST-2']['n'], 2)
        self.runs = [failed(age=25)]
        self.run_epic()
        self.assertEqual(self.watch.state['_infra_retry']['TEST-2']['n'], 3)

    def test_retry_counter_survives_state_save_and_next_tick(self):
        self.run_epic()
        self.watch.save()
        self.watch = c.Watch(False)
        self.run_epic()
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.watch.state['_infra_retry']['TEST-2']['n'], 1)

    def test_pause_prevents_retry_even_after_failure_is_due(self):
        self.controls.write_text('{"paused": true}')
        with self.assertRaises(c.AutomationPaused):
            self.run_epic()
        self.assertEqual(self.writes, [])

    def test_fresh_active_run_or_issue_in_review_prevents_retry(self):
        self.fresh_runs = [{'status': 'queued'}]
        self.run_epic()
        self.assertEqual(self.reads, 2)
        self.assertEqual(self.writes, [])
        self.fresh_runs = None
        self.issue['status'] = 'in_review'
        self.run_epic()
        self.assertEqual(self.writes, [])

    def test_dry_run_and_frozen_do_not_write_or_consume_retry(self):
        self.watch.dry = True
        self.run_epic()
        self.assertEqual(self.watch.state['_infra_retry'], {})
        self.watch.dry = False
        self.run_epic(frozen=True)
        self.assertEqual(self.writes, [])

    def test_configured_interval_and_quota_fallback(self):
        self.epic['quota_retry_minutes'] = 40
        self.run_epic()
        self.assertEqual(self.writes, [])
        self.epic['infra_retry_minutes'] = 20
        self.run_epic()
        self.assertEqual(self.writes, [('issue', 'rerun', 'TEST-2')])

    def test_configured_limit_zero_prevents_rerun(self):
        self.epic['infra_retry_limit'] = 0
        self.run_epic()
        self.assertEqual(self.writes, [])
        self.assertTrue(self.watch.state['_infra_retry']['TEST-2']['gave_up'])


if __name__ == '__main__':
    unittest.main()
