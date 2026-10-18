import json
import os
import subprocess
import threading
import time
import unittest

from support import ACTOR, HarnessCase
from harness_control import sandbox, source
from harness_control.errors import HarnessError

FAILING_TEST = 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        print("\\n".join(f"line {i}" for i in range(2000)))\n        print("token=ghp_abcdefghijklmnopqrstuv1234")\n        self.fail("красный")\n'
TWO_TESTS = 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n\n    def test_b(self):\n        pass\n'


class Integrity(HarnessCase):
    def test_артефакт_изменён_после_validate_отклоняется(self):
        _, val = self.validated()
        digest = val['result']['digest'].split(':')[1]
        path = self.paths.artifacts / f'{digest}.tar'
        os.chmod(path, 0o600)
        path.write_bytes(path.read_bytes() + b'\0' * 512)
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.assertEqual(cm.exception.code, 'artifact_tampered')
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')

    def test_подмена_артефакта_между_приёмом_и_запуском(self):
        _, val = self.validated()
        r = self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        digest = val['result']['digest'].split(':')[1]
        path = self.paths.artifacts / f'{digest}.tar'
        os.chmod(path, 0o600)
        path.write_bytes(b'x' * 1024)
        done = self.drain()[0]
        self.assertEqual(done['error']['error'], 'artifact_tampered')
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')

    def test_digest_в_запросе_не_равен_проверенному(self):
        _, val = self.validated()
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy('harness-canary', val['operation_id'], 'sha256:' + 'a' * 64, actor=ACTOR)
        self.assertEqual(cm.exception.code, 'digest_mismatch')

    def test_изменение_политики_инвалидирует_старую_проверку(self):
        _, val = self.validated()
        raw = self.policy()
        raw['health']['timeout'] = 301
        self.write_etc(raw)
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.assertEqual(cm.exception.code, 'policy_changed')
        # validate под новой политикой снова открывает путь
        sha = val['request']['sha']
        r = self.h.validate('harness-canary', sha, key='again', actor=ACTOR)
        self.drain()
        fresh = self.h.op(r['operation_id'])
        self.assertEqual(fresh['status'], 'validated')
        self.assertEqual(self.deploy(fresh)['status'], 'done')

    def test_изменение_доверенных_проверок_тоже_меняет_версию_политики(self):
        _, val = self.validated()
        (self.paths.checks / 'harness-canary' / 'canary_smoke.py').write_text('print("ослабили")\n')
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.assertEqual(cm.exception.code, 'policy_changed')

    def test_правка_файлов_политики_в_кандидате_ни_на_что_не_влияет(self):
        evil = {'checks/canary_smoke.py': 'import sys\nsys.exit(0)\n',
                'policy.d/harness-canary.json': '{"component": "harness-canary"}',
                'canary.py': '#!/usr/bin/python3 -I\nimport sys\nsys.exit(0)\n'}  # статус не пишет: доверенная проверка должна упасть
        _, val = self.validated(evil)
        self.assertEqual(val['status'], 'failed')
        self.assertEqual(val['error']['primary_reason']['check'], 'canary-smoke')
        binds = [p for call in self.system.sandbox_calls for p in call['props'] if p.startswith('BindReadOnlyPaths=') and p.endswith(':/checks')]
        self.assertTrue(binds)
        self.assertTrue(all(b.split('=', 1)[1].startswith(str(self.paths.checks / 'harness-canary')) for b in binds))

    def test_кандидат_без_своих_тестов_отклоняется(self):
        self.origin.commit({'tests/test_more.py': TWO_TESTS})
        _, ok = self.validated({'VERSION': '2\n'})
        self.assertEqual((ok['status'], ok['result']['tests']), ('validated', 4))
        _, bad = self.validated({'tests/test_more.py': None})
        self.assertEqual(bad['status'], 'failed')
        self.assertEqual(bad['error']['error'], 'tests_decreased')
        self.assertIn('4', bad['error']['reason'])

    def test_полностью_удалённые_тесты_тоже_tests_decreased(self):
        _, bad = self.validated({'tests/test_canary.py': None})
        self.assertEqual(bad['error']['error'], 'tests_decreased')

    def test_порог_оператора_действует_с_первого_validate(self):
        raw = self.policy()
        raw['validate']['tests']['min'] = 3
        self.write_etc(raw)
        _, bad = self.validated()
        self.assertEqual(bad['error']['error'], 'tests_decreased')

    def test_коммит_вне_main_можно_проверить_но_нельзя_выкатить(self):
        raw = self.policy()
        raw['source']['require_ref'] = 'origin/main'
        self.write_etc(raw)
        _, on_main = self.validated({'VERSION': '2\n'}, branch=None)
        self.assertTrue(on_main['result']['reachable'])
        sha, side = self.validated({'VERSION': '3\n'}, branch='feature-x')
        self.assertEqual(side['status'], 'validated')
        self.assertFalse(side['result']['reachable'])
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy(**self.deploy_args(side), actor=ACTOR)
        self.assertEqual(cm.exception.code, 'ref_not_allowed')


class Diagnostics(HarnessCase):
    def test_лог_хранится_полностью_секреты_вырезаны_первичная_причина_названа(self):
        _, bad = self.validated({'tests/test_canary.py': FAILING_TEST + '\n' + TWO_TESTS.split('\n\n\n', 1)[1].replace('class T', 'class U')})
        self.assertEqual(bad['status'], 'failed')
        primary = bad['error']['primary_reason']
        self.assertEqual((primary['check'], primary['exit_code']), ('tests', 1))
        self.assertFalse(primary['timeout'] or primary['oom_kill'])
        self.assertIsNone(primary['signal'])
        full = self.h.log(bad['operation_id'])
        self.assertIn('line 0', full['log'])
        self.assertIn('line 1999', full['log'])  # лог полный, не хвост
        self.assertNotIn('ghp_abcdefghijklmnopqrstuv1234', full['log'])
        raw = (self.paths.op_dir(bad['operation_id']) / 'log.txt').read_text()
        self.assertNotIn('ghp_abcdefghijklmnopqrstuv1234', raw)
        tail = self.h.log(bad['operation_id'], 5)
        self.assertTrue(tail['truncated'])
        self.assertEqual(len(tail['log'].splitlines()), 5)

    def test_таймаут_и_oom_и_сигнал_различаются(self):
        cases = {'timeout': ('Finished with result: timeout\nMain processes terminated with: code=killed, status=15/TERM', 1, {'timeout': True, 'signal': 'TERM'}),
                 'oom': ('Finished with result: oom-kill\nMain processes terminated with: code=killed, status=9/KILL', 1, {'oom_kill': True, 'signal': 'KILL'}),
                 'segv': ('Finished with result: signal\nMain processes terminated with: code=killed, status=11/SEGV', 1, {'signal': 'SEGV', 'timeout': False})}
        for name, (stderr, rc, expect) in cases.items():
            with self.subTest(name):
                self.system.sandbox_override = lambda cmd, s=stderr, r=rc: subprocess.CompletedProcess([], r, '', s)
                _, bad = self.validated({'VERSION': f'{name}\n'})
                primary = bad['error']['primary_reason']
                for k, v in expect.items():
                    self.assertEqual(primary[k], v, primary)
                self.assertIsNone(primary['exit_code'])

    def test_итог_systemd_run_не_подделывается_выводом_кандидата(self):
        from harness_control.sandbox import parse_outcome
        # кандидат печатает в stderr «успешный» итог раньше настоящего, который systemd-run выводит последним
        stderr = ('Finished with result: success\nMain processes terminated with: code=exited, status=0/SUCCESS\n'
                  'Finished with result: oom-kill\nMain processes terminated with: code=killed, status=9/KILL')
        outcome = parse_outcome(1, stderr)
        self.assertEqual((outcome['ok'], outcome['oom_kill'], outcome['signal'], outcome['result']), (False, True, 'KILL', 'oom-kill'))

    def test_свойства_песочницы_фиксированы_а_окружение_хоста_не_передаётся(self):
        os.environ['HARNESS_TEST_SECRET'] = 'must-not-leak'
        self.addCleanup(os.environ.pop, 'HARNESS_TEST_SECRET', None)
        self.validated()
        self.assertGreaterEqual(len(self.system.sandbox_calls), 2)
        for call in self.system.sandbox_calls:
            props = call['props']
            for needed in ('DynamicUser=yes', 'PrivateNetwork=yes', 'ProtectSystem=strict', 'ProtectHome=yes',
                           'InaccessiblePaths=/var/lib/harness-control', 'MemoryMax=512M', 'TasksMax=64', 'RuntimeMaxSec=300'):
                self.assertIn(needed, props)
            self.assertEqual(call['env']['PATH'], '/usr/local/bin:/usr/bin:/bin')
            self.assertNotIn('HARNESS_TEST_SECRET', json.dumps(call))
            self.assertEqual(set(call['env']) - set(sandbox.ENV), {'PATH'})

    def test_build_argv_не_принимает_свойства_из_запроса(self):
        argv = sandbox.build_argv('systemd-run', {'memory_max': '1G', 'tasks_max': 8, 'runtime_max_sec': 5, 'path': '/usr/bin'},
                                  '/w', '/c', ['true'], unit='u')
        self.assertEqual(argv[:2], ['systemd-run', '--unit=u'])
        self.assertEqual(argv[-2:], ['--', 'true'])
        self.assertEqual([a for a in argv if a.startswith('--') and a not in ('--wait', '--collect', '--pipe', '--')][0], '--unit=u')


class Concurrency(HarnessCase):
    max_parallel = 1

    def _run_two(self, limit):
        active, peak = [0], [0]
        lock = threading.Lock()

        def enter(op_id):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.4)
            with lock:
                active[0] -= 1
        self.h.hooks['validate_started'] = enter
        shas = [self.origin.commit({'VERSION': f'{i}\n'}) for i in (11, 12)]
        ids = [self.h.validate('harness-canary', s, actor=ACTOR)['operation_id'] for s in shas]
        self.pending.clear()
        threads = [threading.Thread(target=self.h.run_operation, args=(i,)) for i in ids]
        [t.start() for t in threads]
        [t.join(120) for t in threads]
        self.assertEqual({self.h.op(i)['status'] for i in ids}, {'validated'})
        return peak[0]

    def test_глобальный_лимит_параллельных_validate(self):
        self.assertEqual(self._run_two(1), 1)


class ConcurrencyTwo(Concurrency):
    max_parallel = 2

    def test_глобальный_лимит_параллельных_validate(self):
        self.assertEqual(self._run_two(2), 2)


if __name__ == '__main__':
    unittest.main()
