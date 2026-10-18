import os
import threading
import time
import unittest

from support import ACTOR, HarnessCase, SimulatedCrash, add_component
from harness_control.activate import Owner
from harness_control.errors import HarnessError


def crash(*a):
    raise SimulatedCrash()


class Crashes(HarnessCase):
    def test_падение_после_staging_до_активации_оставляет_старую_версию(self):
        _, val = self.validated({'VERSION': '31\n'})
        r = self.h.deploy(**self.deploy_args(val), key='k', actor=ACTOR)
        self.h.hooks['staged'] = crash
        with self.assertRaises(SimulatedCrash):
            self.h.run_operation(r['operation_id'])
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'staged')
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        report = self.h.recover()['recovered']
        self.assertEqual(report[0]['action'], 'interrupted')
        op = self.h.op(r['operation_id'])
        self.assertEqual(op['status'], 'interrupted')
        self.assertIn('recover', op['events'][-1]['note'])
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        # после recover тот же запрос можно повторить
        del self.h.hooks['staged']
        self.assertEqual(self.deploy(val, key='k')['status'], 'done')

    def test_падение_между_заменой_файлов_recover_возвращает_полный_старый_набор(self):
        old_py = self.dst('canary.py').read_text()
        _, val = self.validated({'VERSION': '32\n', 'canary.py': old_py + '\n# новая версия\n'})
        r = self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.h.hooks['forward:replaced'] = lambda i: crash() if i == 0 else None
        with self.assertRaises(SimulatedCrash):
            self.h.run_operation(r['operation_id'])
        # набор перемешан: canary.py уже новый, VERSION ещё старый
        self.assertIn('новая версия', self.dst('canary.py').read_text())
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        report = self.h.recover()['recovered'][0]
        self.assertEqual(report['restored_files'], 1)
        self.assertEqual(self.dst('canary.py').read_text(), old_py)
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        self.assertEqual([f for f in os.listdir(self.dst('VERSION').parent) if '.tmp-' in f], [])
        op = self.h.op(r['operation_id'])
        self.assertEqual(op['status'], 'interrupted')
        self.assertIn('восстановлен прежний набор', op['events'][-1]['note'])
        self.assertIn('recover', self.h.log(r['operation_id'])['log'])
        info = self.h.inspect('harness-canary')['components'][0]
        self.assertTrue(info['drift']['clean'])
        self.assertFalse(info['locked'])

    def test_падение_после_замены_всех_файлов_до_health_тоже_возвращает_старое(self):
        _, val = self.validated({'VERSION': '33\n'})
        r = self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.h.hooks['forward:switched'] = crash
        with self.assertRaises(SimulatedCrash):
            self.h.run_operation(r['operation_id'])
        self.assertEqual(self.dst('VERSION').read_text().strip(), '33')
        self.h.recover()
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'interrupted')

    def test_recover_не_трогает_работающий_runner(self):
        _, val = self.validated({'VERSION': '34\n'})
        r = self.h.deploy(**self.deploy_args(val), actor=ACTOR)
        self.system.units[f'harness-op-{r["operation_id"]}.service'] = {'ActiveState': 'active'}
        report = self.h.recover()['recovered'][0]
        self.assertEqual(report['action'], 'skipped')
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'queued')


class UnsafeTargets(HarnessCase):
    def _deploy_failed(self):
        _, val = self.validated({'VERSION': '41\n'})
        return self.deploy(val)

    def test_цель_симлинк(self):
        elsewhere = self.tmp / 'elsewhere'
        elsewhere.write_text('чужой файл\n')
        self.dst('VERSION').unlink()
        self.dst('VERSION').symlink_to(elsewhere)
        op = self._deploy_failed()
        self.assertEqual(op['error']['error'], 'unsafe_target')
        self.assertEqual(elsewhere.read_text(), 'чужой файл\n')
        self.assertTrue(self.dst('VERSION').is_symlink())
        self.assertEqual(self.dst('canary.py').read_text(), (self.paths.root / 'usr/local/lib/harness-canary/canary.py').read_text())

    def test_каталог_цели_симлинк(self):
        real = self.dst('VERSION').parent
        moved = self.tmp / 'moved'
        real.rename(moved)
        real.symlink_to(moved)
        self.assertEqual(self._deploy_failed()['error']['error'], 'unsafe_target')
        self.assertEqual((moved / 'VERSION').read_text().strip(), '0')

    def test_каталог_цели_доступен_на_запись_не_владельцу(self):
        os.chmod(self.dst('VERSION').parent, 0o777)
        op = self._deploy_failed()
        self.assertEqual(op['error']['error'], 'unsafe_target')
        self.assertIn('доступен на запись', op['error']['reason'])
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')

    def test_каталог_цели_принадлежит_не_root(self):
        self.h.owner = Owner(os.getuid() + 4242, os.getgid())
        op = self._deploy_failed()
        self.assertEqual(op['error']['error'], 'unsafe_target')
        self.assertIn('принадлежит uid', op['error']['reason'])

    def test_небезопасная_цель_не_оставляет_остановленными_таймеры(self):
        self.system.units['harness-canary.timer']['ActiveState'] = 'active'
        os.chmod(self.dst('VERSION').parent, 0o777)
        self._deploy_failed()
        self.assertIn('harness-canary.timer', self.system.calls_of('start'))


class Serialization(HarnessCase):
    def test_два_deploy_одного_компонента_идут_строго_последовательно(self):
        _, a = self.validated({'VERSION': '51\n'})
        _, b = self.validated({'VERSION': '52\n'})
        log, lock = [], threading.Lock()

        def enter(i):
            if i == -1:
                with lock:
                    log.append('enter')
                time.sleep(0.4)

        def leave(op_id):
            with lock:
                log.append('exit')
        self.h.hooks['forward:journaled'] = enter
        self.h.hooks['forward:switched'] = leave
        ids = [self.h.deploy(**self.deploy_args(v), actor=ACTOR)['operation_id'] for v in (a, b)]
        self.pending.clear()
        threads = [threading.Thread(target=self.h.run_operation, args=(i,)) for i in ids]
        [t.start() for t in threads]
        [t.join(120) for t in threads]
        self.assertEqual(log, ['enter', 'exit', 'enter', 'exit'])
        self.assertEqual({self.h.op(i)['status'] for i in ids}, {'done'})
        info = self.h.inspect('harness-canary')['components'][0]
        self.assertTrue(info['drift']['clean'], 'файлы разных релизов не должны перемешаться')

    def test_deploy_разных_компонентов_друг_друга_не_ждут(self):
        add_component(self, 'harness-canary-b')
        sha_a = self.origin.commit({'VERSION': '61\n'})
        ra = self.h.validate('harness-canary', sha_a, actor=ACTOR)
        rb = self.h.validate('harness-canary-b', sha_a, actor=ACTOR)
        self.drain()
        va, vb = self.h.op(ra['operation_id']), self.h.op(rb['operation_id'])
        self.assertEqual((va['status'], vb['status']), ('validated', 'validated'), (va.get('error'), vb.get('error')))
        barrier = threading.Barrier(2, timeout=20)
        self.h.hooks['forward:journaled'] = lambda i: barrier.wait() if i == -1 else None
        da = self.h.deploy('harness-canary', va['operation_id'], va['result']['digest'], actor=ACTOR)['operation_id']
        db = self.h.deploy('harness-canary-b', vb['operation_id'], vb['result']['digest'], actor=ACTOR)['operation_id']
        self.pending.clear()
        threads = [threading.Thread(target=self.h.run_operation, args=(i,)) for i in (da, db)]
        [t.start() for t in threads]
        [t.join(60) for t in threads]
        self.assertEqual([self.h.op(i)['status'] for i in (da, db)], ['done', 'done'])


class Busy(HarnessCase):
    def test_идущий_тик_не_прерывается(self):
        self.system.units['harness-canary.timer']['ActiveState'] = 'active'
        _, val = self.validated({'VERSION': '71\n'})
        self.system.units['harness-canary.service']['ActiveState'] = 'active'
        op = self.deploy(val)
        self.assertEqual(op['error']['error'], 'busy')
        self.assertEqual(self.dst('VERSION').read_text().strip(), '0')
        self.assertIn('harness-canary.timer', self.system.calls_of('start'))
        self.assertEqual(self.system.calls_of('restart'), [])


if __name__ == '__main__':
    unittest.main()
