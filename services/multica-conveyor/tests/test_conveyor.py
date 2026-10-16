"""Изолированные проверки: Multica подменена целиком, Git — только во временных каталогах."""
import copy
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader('conveyor', str(ROOT / 'multica-conveyor'))
spec = importlib.util.spec_from_loader(loader.name, loader)
c = importlib.util.module_from_spec(spec)
loader.exec_module(c)


class FakeMultica:
    def __init__(self):
        self.issues = {'pkg': {'identifier': 'pkg', 'id': 'pkg', 'status': 'backlog',
                               'assignee_id': None, 'description': ''}}
        self.runs = {}
        self.wakeups = {}
        self.writes = []
        self.uncertain = None

    def __call__(self, *args, write=False):
        if write:
            self.writes.append(args)
            if self.uncertain == 'before':
                raise TimeoutError('ответ не получен')
            if args[:2] == ('issue', 'update'):
                issue = self.issues[args[2]]
                for flag, field in (('--status', 'status'), ('--assignee-id', 'assignee_id')):
                    if flag in args:
                        issue[field] = args[args.index(flag) + 1]
                if '--assignee-id' in args:
                    self.runs[args[2]] = [{'status': 'queued'}]
            if self.uncertain == 'after':
                raise TimeoutError('запись принята, ответ потерян')
            return {}
        if args[:2] == ('issue', 'children'):
            return {'stages': [{'stage': 1, 'issues': copy.deepcopy(list(self.issues.values()))}]}
        if args[:2] == ('issue', 'get'):
            return copy.deepcopy(self.issues[args[2]])
        if args[:2] == ('issue', 'runs'):
            return copy.deepcopy(self.runs.get(args[2], []))
        if args[:3] == ('issue', 'wakeup', 'list'):
            return copy.deepcopy(self.wakeups.get(args[3], []))
        if args[:3] == ('issue', 'comment', 'list'):
            return [{'author_type': 'agent', 'content': 't-12345-delivery'}]
        raise AssertionError(f'Непредусмотренный вызов: {args}')


class FakeRepo:
    base = 'dev'

    def __init__(self):
        self.merged_value = False
        self.accepts = 0
        self.merges = 0
        self.ok = True
        self.head_value = 'a'
        self.after_accept = lambda: None

    def head(self, ref):
        return self.head_value

    def merged(self, branch):
        return self.merged_value

    def accept(self, *args):
        self.accepts += 1
        self.after_accept()
        return self.ok, 'результат проверки', 'журнал'

    def merge(self, *args):
        self.merges += 1
        self.merged_value = True


class ConveyorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name, 'state.json')
        self.env = patch.dict(os.environ, {'MULTICA_CONTROL_STATE': str(Path(self.tmp.name, 'controls.json'))})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.state_patch = patch.object(c, 'STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.api = FakeMultica()
        self.repo = FakeRepo()
        self.epic = {'key': 'epic', 'workspace': 'workspace', 'squad_id': 'squad',
                     'repo': '/unused', 'base': 'dev', 'coordinator': 'external'}

    def tick(self, dry=False, frozen=False):
        with patch.object(c, 'Multica', return_value=self.api), patch.object(c, 'Repo', return_value=self.repo):
            w = c.Watch(dry)
            w.target_key = 'epic'
            c.run_epic(self.epic, w, {'epics': []}, frozen=frozen)
            w.save()

    def review(self):
        self.api.issues['pkg'].update(status='in_review', assignee_id='squad')

    def test_atomic_dispatch_and_event_replay_after_restart(self):
        self.tick()
        self.tick()
        self.assertEqual(self.api.writes, [('issue', 'update', 'pkg', '--assignee-id', 'squad', '--status', 'todo')])

    def test_lost_response_does_not_repeat_committed_assignment(self):
        self.api.uncertain = 'after'
        with self.assertRaises(TimeoutError):
            self.tick()
        self.api.uncertain = None
        self.tick()
        self.assertEqual(len(self.api.writes), 1)

    def test_uncertain_dispatch_fails_closed_on_restart(self):
        self.api.uncertain = 'before'
        with self.assertRaises(TimeoutError):
            self.tick()
        self.api.uncertain = None
        self.tick()
        self.assertEqual(len(self.api.writes), 1)

    def test_active_or_waiting_executor_blocks_dispatch(self):
        for status in ('queued', 'running', 'dispatched', 'pending', 'preparing', 'waiting_local_directory'):
            with self.subTest(status=status):
                self.api.runs['pkg'] = [{'status': status}]
                self.tick()
                self.assertEqual(self.api.writes, [])

    def test_active_run_in_closed_previous_package_blocks_new_dispatch(self):
        self.api.issues['previous'] = {'identifier': 'previous', 'status': 'done', 'assignee_id': 'squad'}
        self.api.runs['previous'] = [{'status': 'running'}]
        self.tick()
        self.assertEqual(self.api.writes, [])

    def test_enabled_wakeup_blocks_dispatch(self):
        self.api.wakeups['pkg'] = [{'enabled': True}]
        self.tick()
        self.assertEqual(self.api.writes, [])

    def test_start_conditions_block_dispatch(self):
        for marker in ('**Ждёт:** доступ', 'Ждёт: ответ', '**Ждет**: решение'):
            with self.subTest(marker=marker):
                self.api.issues['pkg']['description'] = marker
                self.tick()
                self.assertEqual(self.api.writes, [])

    def test_new_work_is_not_assigned_from_in_progress(self):
        self.api.issues['pkg']['status'] = 'in_progress'
        self.tick()
        self.assertEqual(self.api.writes, [])

    def test_one_new_run_blocks_second_dispatch_in_same_tick(self):
        self.api.issues['other'] = {'identifier': 'other', 'status': 'backlog', 'assignee_id': None}
        self.tick()
        self.assertEqual(len(self.api.writes), 1)

    def test_squad_or_missing_coordinator_and_main_never_write(self):
        for coordinator, base in (('squad', 'dev'), (None, 'dev'), ('external', 'main'), ('external', 'master')):
            with self.subTest(coordinator=coordinator, base=base):
                self.epic.update(coordinator=coordinator, base=base)
                self.review()
                self.tick()
                self.assertEqual(self.api.writes, [])
                self.assertEqual(self.repo.accepts, 0)
                self.assertEqual(self.repo.merges, 0)

    def test_acceptance_and_replay_do_not_repeat_merge(self):
        self.review()
        self.tick()
        self.tick()
        self.assertEqual(self.repo.accepts, 1)
        self.assertEqual(self.repo.merges, 1)
        self.assertEqual(self.api.issues['pkg']['status'], 'done')

    def test_active_executor_blocks_acceptance(self):
        self.review()
        self.api.runs['pkg'] = [{'status': 'waiting_local_directory'}]
        self.tick()
        self.assertEqual(self.repo.accepts, 0)
        self.assertEqual(self.api.writes, [])

    def test_failed_acceptance_is_not_repeated_after_restart(self):
        self.review()
        self.repo.ok = False
        self.tick()
        self.review()  # повторная доставка сдачи той же пары коммитов
        self.tick()
        self.assertEqual(self.repo.accepts, 1)
        self.assertEqual(self.repo.merges, 0)
        self.assertEqual(len(self.api.writes), 2)

    def test_restart_after_merge_before_status_write(self):
        self.review()
        self.api.uncertain = 'before'
        with self.assertRaises(TimeoutError):
            self.tick()
        self.api.uncertain = None
        self.tick()
        self.assertEqual(self.repo.accepts, 1)
        self.assertEqual(self.repo.merges, 1)
        self.assertEqual(self.api.issues['pkg']['status'], 'done')

    def test_moved_branch_is_not_merged(self):
        self.review()
        self.repo.after_accept = lambda: setattr(self.repo, 'head_value', 'changed')
        self.tick()
        self.assertEqual(self.repo.merges, 0)
        self.assertEqual(self.api.writes, [])

    def test_dry_run_and_paused_target_never_write_or_check(self):
        self.review()
        self.tick(dry=True)
        self.tick(frozen=True)
        self.assertEqual(self.repo.accepts, 0)
        self.assertEqual(self.api.writes, [])

    def test_deleted_branch_blocks_review_but_not_done_issue(self):
        done = {'identifier': 'a', 'status': 'done'}
        review = {'identifier': 'b', 'status': 'in_review'}
        c.mark_unmerged([{'stage': 1, 'issues': [done, review]}], lambda issue: ['t-1-gone'],
                        lambda branch: False, lambda branch: False)
        self.assertNotIn('unmerged', done)
        self.assertEqual(review['unmerged'], ['t-1-gone'])

    def test_corrupt_state_fails_closed(self):
        self.state.write_text('{broken')
        with self.assertRaises(ValueError):
            c.Watch(False)

    def test_failed_atomic_save_preserves_previous_state(self):
        self.state.write_text('{"before": true}')
        w = c.Watch(False)
        w.state['after'] = True
        with patch.object(c.os, 'replace', side_effect=OSError('диск недоступен')):
            with self.assertRaises(OSError):
                w.save()
        self.assertEqual(json.loads(self.state.read_text()), {'before': True})

    def test_run_lock_blocks_another_process(self):
        with c.run_lock(self.state) as acquired:
            self.assertTrue(acquired)
            code = ('import fcntl,sys; f=open(sys.argv[1],"a"); '
                    'fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)')
            result = subprocess.run([sys.executable, '-c', code, str(self.state.with_suffix('.run.lock'))],
                                    capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        with c.run_lock(self.state) as acquired:
            self.assertTrue(acquired)


class GitAcceptanceTests(unittest.TestCase):
    def test_fresh_clone_checks_and_missing_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                return subprocess.run(['git', '-C', directory, *args], check=True, capture_output=True, text=True)
            git('init', '-b', 'dev')
            git('config', 'user.name', 'Local test')
            git('config', 'user.email', 'test@example.invalid')
            Path(directory, 'base').write_text('base')
            git('add', 'base')
            git('commit', '-m', 'base')
            git('switch', '-c', 't-12345-delivery')
            Path(directory, 'feature').write_text('feature')
            git('add', 'feature')
            git('commit', '-m', 'feature')
            git('switch', 'dev')
            repo = c.Repo(directory, 'dev')
            self.assertFalse(repo.merged('missing'))
            self.assertFalse(repo.accept('t-12345-delivery', ['exit 1'], 10)[0])
            self.assertTrue(repo.accept('t-12345-delivery', ['test -f feature && test -f base'], 10)[0])
            repo.merge('t-12345-delivery', 'local check')
            self.assertTrue(repo.merged('t-12345-delivery'))


if __name__ == '__main__':
    unittest.main()
