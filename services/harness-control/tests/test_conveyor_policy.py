"""Боевая политика сторожа на настоящих исходниках services/multica-conveyor (песочница и systemctl подменены)."""
import datetime as dt
import json
import os
import shutil
import unittest
from pathlib import Path

from support import ACTOR, PKG, HarnessCase, OriginRepo, git

CONVEYOR = PKG.parent / 'multica-conveyor'


def tick_writer(root, relative, lane_errors=()):
    def effect(system):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.fromtimestamp(system.now, dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        path.write_text(json.dumps({'tick': stamp, 'errors': list(lane_errors), 'events': []}))
        return 'success'
    return effect


@unittest.skipUnless(Path('/usr/local/bin/subs-pick').exists(), 'нет установленного subs-pick (проверка subs-pick-smoke)')
class ConveyorComponent(HarnessCase):
    component = 'multica-conveyor'
    install = False

    def setUp(self):
        super().setUp()
        self.install_conveyor()

    def policy(self):
        raw = json.loads((PKG / 'policy.d' / 'multica-conveyor.json').read_text())
        raw['source']['repo'] = str(self.origin.path)
        raw['source']['require_ref'] = 'origin/main'
        raw['health']['poll'] = 5
        raw['health']['commands'] = []  # зависят от установленного на хосте subs-pick; в боевой политике они есть
        return raw

    def write_etc(self, raw=None):
        super().write_etc(raw)
        (self.paths.policy_dir / 'harness-canary.json').unlink()
        (self.paths.policy_dir / 'multica-conveyor.json').write_text(json.dumps(raw or self.policy(), indent=1))

    def build_lib(self):
        super().build_lib()

    def install_conveyor(self):
        # источник: настоящие файлы сервиса в корне временного репо
        repo = self.origin.path
        shutil.rmtree(repo / 'services', ignore_errors=True)
        shutil.copytree(CONVEYOR, repo / 'services/multica-conveyor', ignore=shutil.ignore_patterns('__pycache__', 'systemd'))
        git(repo, 'add', '-A')
        git(repo, 'commit', '-q', '-m', 'conveyor')
        self.sha = git(repo, 'rev-parse', 'HEAD')
        # установленное «до»: другие файлы, чтобы deploy действительно что-то менял
        for dst, text in (('usr/local/bin/multica-conveyor', '#!/bin/sh\n# baseline\n'), ('usr/local/bin/control_state.py', '# baseline\n'),
                          ('opt/multica-control/control_state.py', '# baseline\n')):
            f = self.root / dst
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
            f.chmod(0o755 if 'conveyor' in dst else 0o644)
            os.chmod(f.parent, 0o755)
        s = self.system
        s.add_service('multica-conveyor.service', 'multica-conveyor.timer', 120)
        s.add_service('multica-provider.service', 'multica-provider.timer', 60)
        s.add_service('multica-control.service')
        s.tick_effects['multica-conveyor.service'] = tick_writer(self.root, 'home/agents/.local/state/multica-conveyor/status/status.json')
        s.tick_effects['multica-provider.service'] = tick_writer(self.root, 'home/agents/.local/state/multica-conveyor/providers-status.json')
        self.h.adopt_baseline('multica-conveyor')

    def conveyor_validate(self):
        r = self.h.validate('multica-conveyor', self.sha, actor=ACTOR)
        self.drain()
        return self.h.op(r['operation_id'])

    def test_validate_проходит_доверенные_проверки_и_свои_тесты(self):
        val = self.conveyor_validate()
        self.assertEqual(val['status'], 'validated', (val.get('error'), self.h.log(val['operation_id'])['log'][-1500:]))
        self.assertEqual(val['result']['capabilities']['lanes'], ['epics', 'providers'])
        self.assertGreaterEqual(val['result']['tests'], 69)
        self.assertEqual([c['check'] for c in val['result']['checks']], ['contract-smoke', 'state-compat', 'subs-pick-smoke', 'tests'])

    def test_deploy_включает_провайдеров_и_не_трогает_пульт_без_изменения_control_state(self):
        val = self.conveyor_validate()
        # control_state в «установленном» совпадает с кандидатом -> пульт перезапускать не нужно
        candidate = (CONVEYOR / 'control_state.py').read_text()
        for dst in ('usr/local/bin/control_state.py', 'opt/multica-control/control_state.py'):
            (self.root / dst).write_text(candidate)
        op = self.deploy(val)
        self.assertEqual(op['status'], 'done', op.get('error') or op.get('result'))
        self.assertNotIn('multica-control.service', self.system.calls_of('restart'))
        self.assertIn(('enable', 'multica-provider.timer'), self.system.calls)
        info = self.h.inspect('multica-conveyor')['components'][0]
        self.assertTrue(info['drift']['clean'])
        self.assertEqual((self.root / 'usr/local/bin/multica-conveyor').read_text(), (CONVEYOR / 'multica-conveyor').read_text())
        self.assertEqual(oct((self.root / 'usr/local/bin/multica-conveyor').stat().st_mode & 0o777), '0o755')
        # откат на baseline выключает полосу провайдеров и возвращает старые файлы
        r = self.h.rollback('multica-conveyor', 'baseline', None, ACTOR)
        self.drain()
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'done')
        self.assertIn(('disable', 'multica-provider.timer'), self.system.calls)
        self.assertEqual((self.root / 'usr/local/bin/multica-conveyor').read_text(), '#!/bin/sh\n# baseline\n')

    def test_изменение_control_state_перезапускает_пульт(self):
        val = self.conveyor_validate()
        op = self.deploy(val)
        self.assertEqual(op['status'], 'done', op.get('error') or op.get('result'))
        self.assertEqual(self.system.calls_of('restart'), ['multica-control.service'])

    def test_сломанный_control_state_не_проходит_validate(self):
        git(self.origin.path, 'switch', '-q', '-c', 'broken')
        (self.origin.path / 'services/multica-conveyor/control_state.py').write_text('raise RuntimeError("битый модуль")\n')
        git(self.origin.path, 'commit', '-qam', 'broken')
        self.sha = git(self.origin.path, 'rev-parse', 'HEAD')
        val = self.conveyor_validate()
        self.assertEqual(val['status'], 'failed')
        self.assertIn(val['error']['primary_reason']['check'], ('contract-smoke', 'state-compat', 'subs-pick-smoke'))


if __name__ == '__main__':
    unittest.main()
