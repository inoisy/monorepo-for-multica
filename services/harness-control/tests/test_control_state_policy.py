"""Боевая политика control-state на настоящих исходниках services/control-state (песочница и systemctl подменены)."""
import json
import os
import shutil
import unittest
from pathlib import Path

from support import ACTOR, PKG, HarnessCase, git

CONTROL = PKG.parent / 'control-state'


@unittest.skipUnless(Path('/usr/local/bin/subs-pick').exists(), 'нет установленного subs-pick (проверка subs-pick-smoke)')
class ControlStateComponent(HarnessCase):
    component = 'control-state'
    install = False

    def setUp(self):
        super().setUp()
        self.install_control_state()

    def policy(self):
        raw = json.loads((PKG / 'policy.d' / 'control-state.json').read_text())
        raw['source']['repo'] = str(self.origin.path)
        raw['source']['require_ref'] = 'origin/main'
        raw['health']['poll'] = 5
        raw['health']['commands'] = []  # зависят от установленного на хосте subs-pick; в боевой политике они есть
        return raw

    def write_etc(self, raw=None):
        super().write_etc(raw)
        (self.paths.policy_dir / 'harness-canary.json').unlink()
        (self.paths.policy_dir / 'control-state.json').write_text(json.dumps(raw or self.policy(), indent=1))

    def install_control_state(self):
        repo = self.origin.path
        shutil.rmtree(repo / 'services', ignore_errors=True)
        shutil.copytree(CONTROL, repo / 'services/control-state', ignore=shutil.ignore_patterns('__pycache__'))
        git(repo, 'add', '-A')
        git(repo, 'commit', '-q', '-m', 'control-state')
        self.sha = git(repo, 'rev-parse', 'HEAD')
        for dst in ('usr/local/bin/control_state.py', 'opt/multica-control/control_state.py'):
            f = self.root / dst
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('# baseline\n')
            f.chmod(0o644)
            os.chmod(f.parent, 0o755)
        self.system.add_service('multica-control.service')
        self.h.adopt_baseline('control-state')

    def control_validate(self):
        r = self.h.validate('control-state', self.sha, actor=ACTOR)
        self.drain()
        return self.h.op(r['operation_id'])

    def test_validate_проходит_доверенные_проверки_и_свои_тесты(self):
        val = self.control_validate()
        self.assertEqual(val['status'], 'validated', (val.get('error'), self.h.log(val['operation_id'])['log'][-1500:]))
        self.assertGreaterEqual(val['result']['tests'], 9)
        self.assertEqual([c['check'] for c in val['result']['checks']], ['state-compat', 'subs-pick-smoke', 'tests'])

    def test_deploy_кладёт_модуль_и_перезапускает_пульт_откат_возвращает(self):
        val = self.control_validate()
        op = self.deploy(val)
        self.assertEqual(op['status'], 'done', op.get('error') or op.get('result'))
        self.assertEqual(self.system.calls_of('restart'), ['multica-control.service'])
        for dst in ('usr/local/bin/control_state.py', 'opt/multica-control/control_state.py'):
            self.assertEqual((self.root / dst).read_text(), (CONTROL / 'control_state.py').read_text())
        r = self.h.rollback('control-state', 'baseline', None, ACTOR)
        self.drain()
        self.assertEqual(self.h.op(r['operation_id'])['status'], 'done')
        self.assertEqual((self.root / 'usr/local/bin/control_state.py').read_text(), '# baseline\n')

    def test_сломанный_control_state_не_проходит_validate(self):
        git(self.origin.path, 'switch', '-q', '-c', 'broken')
        (self.origin.path / 'services/control-state/control_state.py').write_text('raise RuntimeError("битый модуль")\n')
        git(self.origin.path, 'commit', '-qam', 'broken')
        self.sha = git(self.origin.path, 'rev-parse', 'HEAD')
        val = self.control_validate()
        self.assertEqual(val['status'], 'failed')
        self.assertIn(val['error']['primary_reason']['check'], ('state-compat', 'subs-pick-smoke'))


class ControlStatePolicyParses(unittest.TestCase):
    def test_политика_проходит_строгую_схему(self):
        from harness_control.policy import Policy
        raw = (PKG / 'policy.d' / 'control-state.json').read_bytes()
        policy = Policy(json.loads(raw), raw, 'x' * 64, '1')
        self.assertEqual([t['dst'] for t in policy.targets], ['/usr/local/bin/control_state.py', '/opt/multica-control/control_state.py'])
        self.assertFalse((PKG / 'policy.d' / 'multica-conveyor.json').exists())


if __name__ == '__main__':
    unittest.main()
