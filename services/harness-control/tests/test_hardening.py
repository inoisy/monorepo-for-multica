"""Находки независимого ревью привилегированной части: каждая закрыта тестом."""
import os
import sys
import time
import unittest
from unittest import mock

from support import ACTOR, HarnessCase, SimulatedCrash
from harness_control import activate, commands, health, policy, redact, safefile, sandbox, system
from harness_control.errors import HarnessError


class RedactIsLinear(unittest.TestCase):
    def test_злонамеренный_вывод_не_вешает_редакцию(self):
        started = time.monotonic()
        redact.redact('a-' * 150000)
        redact.redact('\n'.join(['a-a-a-a. ' * 100] * 3000))
        redact.redact('token' * 200000)
        self.assertLess(time.monotonic() - started, 5)

    def test_вывод_обрезается_по_строке_и_по_размеру(self):
        out = redact.redact('x' * 10000 + '\n' + 'y' * (3 << 20))
        self.assertLess(len(out), 2 * redact.MAX_TEXT)
        self.assertIn('обрезан', out)

    def test_секреты_по_прежнему_вырезаются(self):
        out = redact.redact('API_KEY=abcdef123456 Authorization: Bearer abcdefghijkl123 ghp_abcdefghijklmnopqrstuv')
        for leaked in ('abcdef123456', 'abcdefghijkl123', 'ghp_abcdefghijklmnopqrstuv'):
            self.assertNotIn(leaked, out)


class SafeFile(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def test_fifo_симлинк_и_гигант_не_читаются(self):
        fifo = os.path.join(self.dir, 'fifo')
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            safefile.read_text(fifo)
        link = os.path.join(self.dir, 'link')
        os.symlink('/dev/zero', link)
        with self.assertRaises(OSError):
            safefile.read_text(link)
        big = os.path.join(self.dir, 'big')
        with open(big, 'wb') as f:
            f.truncate(safefile.LIMIT + 1)
        with self.assertRaises(ValueError):
            safefile.read_text(big)
        ok = os.path.join(self.dir, 'ok')
        with open(ok, 'w') as f:
            f.write('{"a": 1}')
        self.assertEqual(safefile.read_text(ok), '{"a": 1}')


class StatusFromAgent(HarnessCase):
    def evaluate(self, text):
        path = self.root / 'var/lib/harness-canary/status.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        item = self.h.policies.get('harness-canary').health['status_files'][0]
        return self.h.health._status_file(item, 0)

    def test_любой_формат_статуса_это_отказ_проверки_а_не_исключение(self):
        for text in ('{"tick": 1}', '{"tick": "2026-01-01 00:00:00", "errors": [""]}', '{"tick": "2026-01-01 00:00:00", "errors": 5}',
                     '{"tick": "2026-01-01 00:00:00", "errors": {"a": 1}}', '[]', 'null', '{"tick": "2026-01-01 00:00:00", "events": 7}',
                     '{"tick": "2026-01-01 00:00:00", "events": [1, "x", {"t": 3}]}', '\x00\x01'):
            with self.subTest(text=text):
                result = self.evaluate(text)
                self.assertIn(result['state'], ('pass', 'fail', 'pending'))

    def test_inspect_живёт_при_подменённом_статусе(self):
        path = self.root / 'var/lib/harness-canary/status.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)
        started = time.monotonic()
        info = self.h.inspect()
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(info['components'][0]['component'], 'harness-canary')

    def test_inspect_не_падает_целиком_из_за_одного_компонента(self):
        with mock.patch.object(type(self.h), '_inspect_one', side_effect=RuntimeError('сломано')):
            items = self.h.inspect()['components']
        self.assertEqual(items[0]['error'], 'internal')


class AbortRestoresUnits(HarnessCase):
    def policy(self):
        raw = super().policy()
        raw['restart_units'] = [{'unit': 'harness-canary.service', 'when_changed': ['/usr/local/lib/harness-canary/VERSION']}]
        return raw

    def test_сбой_health_возвращает_файлы_перезапускает_юниты_и_поднимает_таймеры(self):
        self.system.units['harness-canary.timer']['ActiveState'] = 'active'
        _, val = self.validated({'VERSION': '2\n'})
        with mock.patch.object(type(self.h.health), 'wait', side_effect=RuntimeError('health сломался')):
            op = self.deploy(val)
        self.assertEqual(op['status'], 'failed')
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        self.assertEqual(self.system.calls_of('restart'), ['harness-canary.service', 'harness-canary.service'])
        self.assertIn('harness-canary.timer', self.system.calls_of('start'))

    def test_падение_после_остановки_таймеров_recover_поднимает_их(self):
        self.system.units['harness-canary.timer']['ActiveState'] = 'active'
        _, val = self.validated({'VERSION': '3\n'})
        r = self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.h.hooks['forward:timers_stopped'] = lambda op_id: (_ for _ in ()).throw(SimulatedCrash())
        with self.assertRaises(SimulatedCrash):
            self.h.run_operation(r['operation_id'])
        self.assertIn(('stop', 'harness-canary.timer'), self.system.calls)
        self.system.calls.clear()
        self.h.recover()
        self.assertIn(('start', 'harness-canary.timer'), self.system.calls)
        self.assertEqual(self.system.calls_of('restart'), [], 'файлы не менялись: перезапуск не нужен')


class WriteIntegrity(HarnessCase):
    def test_короткие_записи_дописываются(self):
        real = os.write
        with mock.patch('os.write', side_effect=lambda fd, data: real(fd, bytes(data)[:3])):
            _, val = self.validated({'VERSION': '4\n'})
            op = self.deploy(val)
        self.assertEqual(op['status'], 'done')
        self.assertEqual(self.dst('VERSION').read_text().strip(), '4')
        self.assertTrue(self.h.inspect('harness-canary')['components'][0]['drift']['clean'])

    def test_усечённая_запись_не_становится_целью(self):
        _, val = self.validated({'VERSION': '5\n'})
        original = activate._write_all
        with mock.patch.object(activate, '_write_all', side_effect=lambda fd, data: original(fd, bytes(data)[:-1])):
            op = self.deploy(val)
        self.assertEqual(op['status'], 'failed')
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        self.assertEqual([f for f in os.listdir(self.dst('VERSION').parent) if '.tmp-' in f], [])


class ReleaseBookkeeping(HarnessCase):
    def test_повторная_запись_релиза_не_сбрасывает_health(self):
        _, val = self.validated({'VERSION': '6\n'})
        self.deploy(val)
        rid = val['result']['digest'].split(':')[1]
        before = self.h.store.release('harness-canary', rid)
        self.h.store.add_release('harness-canary', rid, digest=val['result']['digest'], commit_sha='a' * 40, source='git',
                                 capabilities={'lanes': []}, tests=2, validation_op=val['operation_id'])
        after = self.h.store.release('harness-canary', rid)
        self.assertEqual((after['healthy'], after['deployed_at'], after['deployed_by']), (1, before['deployed_at'], before['deployed_by']))

    def test_deploy_уже_выложенной_версии_ничего_не_меняет(self):
        _, val = self.validated({'VERSION': '7\n'})
        self.deploy(val)
        self.system.calls.clear()
        again = self.deploy(val, key='second')
        self.assertEqual((again['status'], again['result']['noop']), ('done', True))
        self.assertEqual(self.system.calls, [])

    def test_откат_на_релиз_без_health_запрещён(self):
        _, val = self.validated({'VERSION': '8-fail\n'})
        self.assertEqual(self.deploy(val)['status'], 'rolled_back')
        rid = val['result']['digest'].split(':')[1]
        with self.assertRaises(HarnessError) as cm:
            self.h.rollback('harness-canary', rid, actor=ACTOR)
        self.assertEqual(cm.exception.code, 'release_not_found')
        self.assertIn('health', cm.exception.reason)


class TestsBaseline(HarnessCase):
    def policy(self):
        raw = super().policy()
        raw['source']['require_ref'] = 'origin/main'
        return raw

    def test_порог_поднимают_только_коммиты_основной_ветки(self):
        more = 'import unittest\n\n\nclass T(unittest.TestCase):\n' + ''.join(f'    def test_{i}(self): pass\n\n' for i in range(20))
        _, side = self.validated({'tests/test_many.py': more}, branch='side')
        self.assertGreater(side['result']['tests'], 20)
        self.assertEqual(self.h.store.component('harness-canary')['tests_baseline'], 1, 'порог оператора, а не счёт чужой ветки')
        _, ok = self.validated({'VERSION': '2\n'})
        self.assertEqual(ok['status'], 'validated')
        self.assertEqual(self.h.store.component('harness-canary')['tests_baseline'], ok['result']['tests'])


class Queue(HarnessCase):
    def test_очередь_validate_ограничена_повтор_допускается(self):
        shas = [self.origin.commit({'VERSION': f'{i}\n'}) for i in range(9)]
        first = [self.h.validate('harness-canary', s, actor=ACTOR) for s in shas[:8]]
        with self.assertRaises(HarnessError) as cm:
            self.h.validate('harness-canary', shas[8], actor=ACTOR)
        self.assertEqual(cm.exception.code, 'busy')
        replay = self.h.validate('harness-canary', shas[0], actor=ACTOR)
        self.assertEqual(replay['operation_id'], first[0]['operation_id'])


class Inputs(unittest.TestCase):
    def test_завершающий_перевод_строки_не_проходит_регулярки(self):
        for tokens in (['harness-canary\n'], ['multica-agents\n']):
            with self.assertRaises(HarnessError) as cm:
                commands.parse('inspect', tokens)
            self.assertEqual(cm.exception.code, 'bad_request')

    def test_url_репозитория_без_учётных_данных(self):
        import json
        from support import PKG
        raw = json.loads((PKG / 'policy.d' / 'harness-canary.json').read_text())
        for repo in ('https://user:secret@github.com/o/r.git', 'http://github.com/o/r.git', 'git@github.com:o/r.git', 'https://github.com/o/r.git\n'):
            raw['source']['repo'] = repo
            with self.assertRaises(policy.PolicyError, msg=repo):
                policy.Policy._validate(json.loads(json.dumps(raw)))

    def test_свойства_песочницы_расширены(self):
        argv = sandbox.build_argv('systemd-run', {'memory_max': '1G', 'tasks_max': 8, 'runtime_max_sec': 5, 'path': '/usr/bin'}, '/w', '/c', ['true'])
        props = [argv[i + 1] for i, a in enumerate(argv) if a == '-p']
        for needed in ('RestrictNamespaces=yes', 'RestrictAddressFamilies=AF_UNIX', 'ProtectProc=invisible', 'SystemCallFilter=@system-service',
                       'TemporaryFileSystem=/tmp:mode=1777,size=512M', 'LimitFSIZE=1G', 'MemorySwapMax=0'):
            self.assertIn(needed, props)
        self.assertNotIn('PrivateTmp=yes', props)

    def test_вывод_команды_ограничен(self):
        sysm = system.System(mock.Mock(root=mock.Mock(parent=object())), bare=True)
        started = time.monotonic()
        r = sysm.run([sys.executable, '-c', "import sys; sys.stdout.write('x' * (24 << 20)); sys.stderr.write('e' * (24 << 20))"], timeout=60)
        self.assertLessEqual(len(r.stdout), system.MAX_OUTPUT)
        self.assertLessEqual(len(r.stderr), system.MAX_OUTPUT)
        self.assertEqual(r.returncode, 0)
        self.assertLess(time.monotonic() - started, 30)


if __name__ == '__main__':
    unittest.main()
