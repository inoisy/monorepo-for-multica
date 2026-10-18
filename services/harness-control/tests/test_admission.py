import io
import json
import subprocess
import unittest

from support import ACTOR, PKG, HarnessCase
from harness_control import client, policy as policy_mod
from harness_control.errors import HarnessError


class Components(HarnessCase):
    def assertRefused(self, code, fn, *args, **kw):
        with self.assertRaises(HarnessError) as cm:
            fn(*args, **kw)
        self.assertEqual(cm.exception.code, code, cm.exception.reason)
        return cm.exception

    def test_неизвестный_компонент(self):
        sha = '0' * 40
        self.assertRefused('unknown_component', self.h.validate, 'nosuch', sha, actor=ACTOR)
        self.assertRefused('unknown_component', self.h.deploy, 'nosuch', '0000000000000-deadbeef', 'sha256:' + '0' * 64, actor=ACTOR)
        self.assertRefused('unknown_component', self.h.rollback, 'nosuch', actor=ACTOR)
        self.assertRefused('unknown_component', self.h.inspect, 'nosuch')
        err = self.h.handle('inspect', {'component': 'nosuch'}, ACTOR)
        self.assertEqual(err['error'], 'unknown_component')
        self.assertIn('оператор', err['missing'])

    def test_daemon_и_платформа_запрещены_даже_если_политика_лежит_на_диске(self):
        for name in ('multica-agents', 'multica', 'multica-backend', 'harness-control'):
            with self.subTest(name):
                (self.paths.policy_dir / f'{name}.json').write_text(json.dumps({'component': name}))
                for call in (lambda: self.h.validate(name, '0' * 40, actor=ACTOR), lambda: self.h.rollback(name, actor=ACTOR),
                             lambda: self.h.deploy(name, '0000000000000-deadbeef', 'sha256:' + '0' * 64, actor=ACTOR)):
                    self.assertRefused('forbidden_component', call)
        listed = {c['component']: c for c in self.h.inspect()['components']}
        self.assertEqual(listed['multica-agents']['error'], 'forbidden_component')

    def test_политика_с_запрещённым_именем_не_загружается(self):
        raw = self.policy()
        raw['component'] = 'multica-agents'
        with self.assertRaises(policy_mod.PolicyError):
            policy_mod.Policy._validate(raw)

    def test_агенту_недоступны_административные_действия(self):
        for verb, args in (('adopt-baseline', {'component': 'harness-canary'}), ('recover', {}), ('run-op', {'id': '0000000000000-deadbeef'})):
            self.assertEqual(self.h.handle(verb, args, ACTOR)['error'], 'verb_not_allowed', verb)
        self.assertEqual(self.h.handle('rm', {}, ACTOR)['error'], 'verb_not_allowed')
        operator = {'sudo_user': 'evgeniy', 'agent': '', 'task': ''}
        self.assertEqual(self.h.handle('adopt-baseline', {'component': 'harness-canary'}, operator)['baseline'], 'exists')

    def test_аргументы_проверяются_регулярками(self):
        self.assertRefused('bad_request', self.h.validate, 'harness-canary', 'HEAD', actor=ACTOR)
        self.assertRefused('bad_request', self.h.validate, 'harness-canary', '0' * 39, actor=ACTOR)
        self.assertRefused('bad_request', self.h.validate, '../etc', '0' * 40, actor=ACTOR)
        self.assertRefused('bad_request', self.h.validate, 'harness-canary', '0' * 40, 'a b;rm', actor=ACTOR)
        self.assertRefused('bad_request', self.h.validate, 'harness-canary', '0' * 40, None, 'x' * 501, ACTOR)
        self.assertRefused('bad_request', self.h.deploy, 'harness-canary', 'op', 'sha256:' + '0' * 64, actor=ACTOR)
        self.assertRefused('bad_request', self.h.deploy, 'harness-canary', '0000000000000-deadbeef', 'md5:1', actor=ACTOR)
        self.assertRefused('bad_request', self.h.rollback, 'harness-canary', '../../x', actor=ACTOR)
        self.assertRefused('bad_request', self.h.log, '0000000000000-deadbeef', 0)

    def test_reason_только_данные_и_сохраняется_как_есть(self):
        sha = self.origin.commit({'VERSION': '2\n'})
        r = self.h.validate('harness-canary', sha, reason='$(touch /tmp/pwned); `id` && echo', actor=ACTOR)
        self.assertEqual(self.h.op(r['operation_id'])['reason'], '$(touch /tmp/pwned); `id` && echo')

    def test_аудит_пишет_кто_что_и_зачем(self):
        sha = self.origin.commit({'VERSION': '2\n'})
        self.h.handle('validate', {'component': 'harness-canary', 'sha': sha, 'reason': 'проверка аудита'}, ACTOR)
        self.h.handle('validate', {'component': 'nosuch', 'sha': sha}, ACTOR)
        lines = [json.loads(l) for l in self.paths.audit.read_text().splitlines()]
        self.assertEqual(lines[0]['actor'], ACTOR)
        self.assertEqual((lines[0]['verb'], lines[0]['reason'], lines[0]['outcome']), ('validate', 'проверка аудита', 'accepted'))
        self.assertEqual(lines[1]['outcome'], 'unknown_component')


class NotInstalled(HarnessCase):
    install = False

    def test_без_baseline_deploy_и_rollback_не_install(self):
        _, val = self.validated({'VERSION': '2\n'})
        for fn in (lambda: self.h.deploy(**self.deploy_args(val), actor=ACTOR), lambda: self.h.rollback('harness-canary', actor=ACTOR)):
            with self.assertRaises(HarnessError) as cm:
                fn()
            self.assertEqual(cm.exception.code, 'not_installed')
            self.assertIn('оператор', cm.exception.missing)
        info = self.h.inspect('harness-canary')['components'][0]
        self.assertEqual(info['allowed_operations'], ['validate'])

    def test_нет_юнитов_systemd(self):
        self.h.adopt_baseline('harness-canary')
        _, val = self.validated({'VERSION': '2\n'})
        del self.system.units['harness-canary.service']
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.assertEqual(cm.exception.code, 'not_installed')
        self.assertIn('harness-canary.service', cm.exception.reason)


class ClientNotInstalled(unittest.TestCase):
    def test_нет_root_входа_называет_точную_команду_оператора(self):
        result = client.call('inspect', [], exists=lambda p: False)
        self.assertEqual(result['error'], 'not_installed')
        self.assertIn('/usr/local/sbin/harness-priv', result['reason'])
        self.assertRegex(result['missing'], r'^оператор \(root\): sudo bash \S+/bootstrap/install\.sh$')
        self.assertIn(str(PKG / 'bootstrap' / 'install.sh'), result['missing'])

    def test_sudo_требует_пароль(self):
        fake = lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'sudo: a password is required')
        result = client.call('inspect', [], run=fake, exists=lambda p: True)
        self.assertEqual(result['error'], 'not_installed')
        self.assertIn('password', result['reason'])
        self.assertIn('install.sh', result['missing'])

    def test_sudo_вызывается_списком_аргументов_без_shell(self):
        seen = []

        def fake(argv, **kw):
            seen.append((argv, kw))
            return subprocess.CompletedProcess(argv, 0, '{"ok": true}', '')
        client.call('validate', ['harness-canary', 'a' * 40, '--reason', 'x; rm -rf /'], run=fake, exists=lambda p: True)
        argv, kw = seen[0]
        self.assertEqual(argv[:3], ['sudo', '-n', '/usr/local/sbin/harness-priv'])
        self.assertEqual(argv[-1], '--json')
        self.assertIn('x; rm -rf /', argv)
        self.assertFalse(kw.get('shell'))


class PolicyFiles(HarnessCase):
    def test_политика_доступная_на_запись_всем_помечается(self):
        import os
        os.chmod(self.paths.policy_dir / 'harness-canary.json', 0o666)
        self.assertTrue(self.h.inspect()['harness']['policy_problems'])

    def test_политика_со_странным_ключом_отвергается(self):
        raw = self.policy()
        raw['targets'][0]['dst'] = 'relative/path'
        self.write_etc(raw)
        with self.assertRaises(HarnessError) as cm:
            self.h.validate('harness-canary', '0' * 40, actor=ACTOR)
        self.assertEqual(cm.exception.code, 'internal')
        raw = self.policy()
        raw['evil'] = True
        self.write_etc(raw)
        with self.assertRaises(HarnessError):
            self.h.validate('harness-canary', '0' * 40, actor=ACTOR)


if __name__ == '__main__':
    unittest.main()
