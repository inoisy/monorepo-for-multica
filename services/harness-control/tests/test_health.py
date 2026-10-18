import unittest

from support import ACTOR, HarnessCase, canary_effect
from harness_control.errors import HarnessError


class Counting(HarnessCase):
    def setUp(self):
        super().setUp()
        self.switches = []
        for side in ('forward', 'back'):
            self.h.hooks[f'{side}:switched'] = lambda op_id, side=side: self.switches.append(side)


class AutoRollback(Counting):
    def test_health_не_прошёл_ровно_один_автооткат(self):
        _, val = self.validated({'VERSION': '2-fail\n'})
        op = self.deploy(val)
        self.assertEqual(op['status'], 'rolled_back', op)
        self.assertEqual(self.switches, ['forward', 'back'])
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        self.assertEqual(op['result']['failed_release'], val['result']['digest'].split(':')[1])
        self.assertFalse(op['result']['health']['ok'])
        self.assertTrue(op['result']['rollback_health']['ok'])
        info = self.h.inspect('harness-canary')['components'][0]
        self.assertEqual(info['version']['release'], 'baseline')
        self.assertFalse(info['locked'])
        self.assertTrue(info['drift']['clean'])
        # сбойная версия не станет целью rollback по умолчанию
        self.assertEqual(self.h.store.previous_healthy('harness-canary', 'baseline'), None)

    def test_откат_тоже_не_прошёл_health_degraded_и_блокировка(self):
        _, val = self.validated({'VERSION': '3\n'})
        self.system.tick_effects['harness-canary.service'] = lambda s: 'exit-code'
        op = self.deploy(val)
        self.assertEqual(op['status'], 'degraded', op)
        self.assertEqual(self.switches, ['forward', 'back'])  # повторов нет
        self.assertEqual(self.pending, [])
        info = self.h.inspect('harness-canary')['components'][0]
        self.assertTrue(info['locked'])
        self.assertEqual(info['allowed_operations'], ['validate', 'rollback'])
        _, other = self.validated({'VERSION': '4\n'})
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy(**self.deploy_args(other), actor=ACTOR)
        self.assertEqual(cm.exception.code, 'locked_degraded')

    def test_явный_rollback_снимает_блокировку_после_успешного_health(self):
        _, val = self.validated({'VERSION': '3\n'})
        self.system.tick_effects['harness-canary.service'] = lambda s: 'exit-code'
        self.assertEqual(self.deploy(val)['status'], 'degraded')
        self.system.tick_effects['harness-canary.service'] = canary_effect(self.root)
        r = self.h.rollback('harness-canary', None, 'снять блокировку', ACTOR)
        self.drain()
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'done')
        self.assertFalse(self.h.inspect('harness-canary')['components'][0]['locked'])
        _, again = self.validated({'VERSION': '4\n'})
        self.assertEqual(self.deploy(again)['status'], 'done')

    def test_неудачный_явный_rollback_оставляет_degraded_без_повторов(self):
        _, val = self.validated({'VERSION': '3\n'})
        self.assertEqual(self.deploy(val)['status'], 'done')
        self.system.tick_effects['harness-canary.service'] = lambda s: 'exit-code'
        r = self.h.rollback('harness-canary', 'baseline', None, ACTOR)
        self.drain()
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'degraded')
        self.assertEqual(self.switches, ['forward', 'forward'])
        self.assertTrue(self.h.inspect('harness-canary')['components'][0]['locked'])

    def test_нет_планового_тика_в_окне_health_это_провал_с_причиной(self):
        _, val = self.validated({'VERSION': '5\n'})
        self.system.timer_service['harness-canary.timer'] = ('harness-canary.service', 10 ** 6)
        op = self.deploy(val)
        self.assertEqual(op['status'], 'degraded')
        checks = op['result']['health']['checks']
        self.assertIn('не дождались', ' '.join(c['detail'] for c in checks))
        self.assertGreaterEqual(op['result']['health']['waited'], 300)


class HealthRules(HarnessCase):
    def test_лишний_тик_не_запускается_health_только_ждёт(self):
        _, val = self.validated({'VERSION': '6\n'})
        self.deploy(val)
        self.assertEqual([c for c in self.system.calls if c[0] not in ('stop', 'start')], [])

    def test_ошибки_в_статусе_это_провал_даже_при_успехе_юнита(self):
        def effect(system):
            canary_effect(self.root)(system)
            import json
            path = self.root / 'var/lib/harness-canary/status.json'
            status = json.loads(path.read_text())
            status['errors'] = ['RuntimeError: упал на token=ghp_abcdefghijklmnopqrstuv1234']
            path.write_text(json.dumps(status))
            return 'success'
        _, val = self.validated({'VERSION': '7\n'})
        self.system.tick_effects['harness-canary.service'] = effect
        op = self.deploy(val)
        self.assertEqual(op['status'], 'degraded')
        text = str(op['result']['health'])
        self.assertIn('RuntimeError', text)
        self.assertNotIn('ghp_abcdefghijklmnopqrstuv1234', text)

    def test_старый_tick_не_считается_свежим(self):
        _, val = self.validated({'VERSION': '8\n'})
        stale = self.root / 'var/lib/harness-canary/status.json'
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text('{"tick": "2020-01-01 00:00:00", "errors": []}')
        self.system.tick_effects['harness-canary.service'] = lambda s: 'success'  # юнит успешен, но статус не обновляет
        op = self.deploy(val)
        self.assertEqual(op['status'], 'degraded')
        self.assertIn('tick старше активации', str(op['result']['health']))

    def test_http_проверка(self):
        raw = self.policy()
        raw['health']['http'] = [{'url': 'http://127.0.0.1:8098/', 'expect': [302]}]
        self.write_etc(raw)
        self.h = self.make_harness(http=lambda url: 500)
        _, val = self.validated({'VERSION': '9\n'})
        op = self.deploy(val)
        self.assertEqual(op['status'], 'degraded')
        self.assertIn('код 500', str(op['result']['health']))


class Lanes(Counting):
    def policy(self):
        raw = super().policy()
        raw['lanes'] = {'providers': {'timers': ['harness-canary-p.timer']}}
        raw['required_units'] += ['harness-canary-p.service', 'harness-canary-p.timer']
        raw['capabilities'] = {'argv': ['/usr/bin/python3', '-I', '-c', "import json; print(json.dumps({'lanes': ['epics', 'providers']}))"]}
        raw['baseline_capabilities'] = {'lanes': ['epics']}
        raw['health']['units'].append({'unit': 'harness-canary-p.service', 'timer': 'harness-canary-p.timer', 'lane': 'providers'})
        return raw

    def setUp(self):
        super().setUp()
        self.system.add_service('harness-canary-p.service', 'harness-canary-p.timer')

    def test_deploy_включает_полосу_по_capabilities_откат_на_baseline_выключает(self):
        _, val = self.validated({'VERSION': '2\n'})
        self.assertEqual(val['result']['capabilities']['lanes'], ['epics', 'providers'])
        self.assertEqual(self.deploy(val)['status'], 'done')
        self.assertIn(('enable', 'harness-canary-p.timer'), self.system.calls)
        self.assertEqual(self.system.units['harness-canary-p.timer']['ActiveState'], 'active')
        self.assertIsNotNone(self.system.units['harness-canary-p.service']['ExecMainStartTimestamp'], 'health ждёт и полосу провайдеров')
        r = self.h.rollback('harness-canary', 'baseline', None, ACTOR)
        self.drain()
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'done')
        self.assertIn(('disable', 'harness-canary-p.timer'), self.system.calls)
        self.assertEqual(self.system.units['harness-canary-p.timer']['ActiveState'], 'inactive')

    def test_не_установленные_юниты_полосы_это_not_installed(self):
        del self.system.units['harness-canary-p.timer']
        _, val = self.validated({'VERSION': '2\n'})
        with self.assertRaises(HarnessError) as cm:
            self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.assertEqual(cm.exception.code, 'not_installed')
        self.assertIn('install.sh', cm.exception.missing)

    def test_кандидат_без_capabilities_не_проходит_validate(self):
        self.system.sandbox_override = lambda cmd: None if 'canary' in ' '.join(cmd) or 'unittest' in ' '.join(cmd) else \
            __import__('subprocess').CompletedProcess([], 0, 'нет json\n', 'Finished with result: success')
        _, val = self.validated({'VERSION': '3\n'})
        self.assertEqual(val['status'], 'failed')
        self.assertEqual(val['error']['primary_reason']['check'], 'capabilities')


if __name__ == '__main__':
    unittest.main()
