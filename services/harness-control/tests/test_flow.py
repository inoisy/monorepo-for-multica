import json
import unittest

from support import ACTOR, HarnessCase
from harness_control.errors import HarnessError


class ValidateDeploy(HarnessCase):
    def test_validate_deploy_inspect_и_rollback_до_baseline(self):
        sha, val = self.validated({'VERSION': '5\n'})
        self.assertEqual(val['status'], 'validated', val)
        self.assertRegex(val['result']['digest'], r'^sha256:[0-9a-f]{64}$')
        self.assertEqual(val['result']['tests'], 2)
        self.assertEqual(val['result']['commit'], sha)
        dep = self.deploy(val)
        self.assertEqual(dep['status'], 'done', dep)
        self.assertEqual(self.dst('VERSION').read_text().strip(), '5')
        self.assertEqual(oct(self.dst('canary.py').stat().st_mode & 0o777), '0o755')
        info = self.h.inspect('harness-canary')['components'][0]
        self.assertEqual(info['version']['digest'], val['result']['digest'])
        self.assertEqual(info['version']['commit'], sha)
        self.assertTrue(info['drift']['clean'])
        self.assertTrue(info['health']['ok'], info['health'])
        self.assertEqual(info['last_operation']['status'], 'done')
        # откат на baseline
        r = self.h.rollback('harness-canary', None, 'test', ACTOR)
        self.drain()
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'done')
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        self.assertEqual(self.h.inspect('harness-canary')['components'][0]['version']['release'], 'baseline')

    def test_inspect_видит_дрейф_ручной_правки(self):
        self.dst('VERSION').write_text('hand-edit\n')
        info = self.h.inspect('harness-canary')['components'][0]
        self.assertFalse(info['drift']['clean'])
        self.assertEqual([f['ok'] for f in info['drift']['files']], [True, False])

    def test_inspect_без_секретов_и_с_разрешёнными_операциями(self):
        out = json.dumps(self.h.inspect(), ensure_ascii=False)
        for word in ('token', 'password', 'secret'):
            self.assertNotIn(word, out.lower())
        info = self.h.inspect('harness-canary')['components'][0]
        self.assertEqual(info['allowed_operations'], ['validate', 'deploy', 'rollback'])
        self.assertEqual({u['unit'] for u in info['units']}, {'harness-canary.service', 'harness-canary.timer'})

    def test_повтор_с_тем_же_ключом_не_создаёт_второй_deploy(self):
        _, val = self.validated({'VERSION': '6\n'})
        first = self.h.deploy(**self.deploy_args(val), key='k1', reason='r', actor=ACTOR)
        again = self.h.deploy(**self.deploy_args(val), key='k1', reason='r', actor=ACTOR)
        self.assertEqual(first['operation_id'], again['operation_id'])
        self.assertTrue(first['created'])
        self.assertFalse(again['created'])
        self.drain()
        self.assertEqual(len(self.system.calls_of('start')), 1)
        # повтор после выполнения возвращает ту же завершённую операцию, активации по-прежнему одна
        late = self.h.deploy(**self.deploy_args(val), key='k1', reason='r', actor=ACTOR)
        self.assertEqual(late['operation_id'], first['operation_id'])
        self.assertEqual(late['status'], 'done')
        self.assertEqual(self.pending, [])
        self.assertEqual(len(self.system.calls_of('start')), 1)

    def test_тот_же_ключ_с_другим_запросом_отклоняется(self):
        _, a = self.validated({'VERSION': '6\n'})
        _, b = self.validated({'VERSION': '7\n'})
        self.h.deploy(**self.deploy_args(a), key='dup', actor=ACTOR)
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy(**self.deploy_args(b), key='dup', actor=ACTOR)
        self.assertEqual(cm.exception.code, 'idempotency_conflict')

    def test_после_отказа_повтор_с_тем_же_ключом_запускается_заново(self):
        _, val = self.validated({'VERSION': '6\n'})
        self.system.units['harness-canary.service']['ActiveState'] = 'active'
        first = self.deploy(val, key='retry')
        self.assertEqual((first['status'], first['error']['error']), ('failed', 'busy'))
        self.system.units['harness-canary.service']['ActiveState'] = 'inactive'
        second = self.deploy(val, key='retry')
        self.assertNotEqual(first['operation_id'], second['operation_id'])
        self.assertEqual(second['status'], 'done')

    def test_deploy_без_validate_и_с_чужой_validate(self):
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy('harness-canary', '0000000000000-deadbeef', 'sha256:' + '0' * 64, actor=ACTOR)
        self.assertEqual(cm.exception.code, 'validation_not_found')
        _, val = self.validated({'VERSION': '5\n'})
        failed_sha = self.origin.commit({'tests/test_canary.py': 'import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.fail("x")\n'})
        r = self.h.validate('harness-canary', failed_sha, actor=ACTOR)
        self.drain()
        bad = self.h.op(r['operation_id'])
        self.assertEqual(bad['status'], 'failed')
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy('harness-canary', bad['operation_id'], val['result']['digest'], actor=ACTOR)
        self.assertEqual(cm.exception.code, 'validation_failed')


if __name__ == '__main__':
    unittest.main()
