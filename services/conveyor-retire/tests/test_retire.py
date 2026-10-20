"""Снятие сторожа: перенос целей в multica и снятие с хоста (корень и systemctl подменены, multica — фальшивый)."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader('epics_to_stages', str(HERE / 'epics-to-stages'))
spec = importlib.util.spec_from_loader('epics_to_stages', loader)
ets = importlib.util.module_from_spec(spec)
loader.exec_module(ets)


class FakeMultica:
    def __init__(self):
        self.calls = []
        self.children = {'stages': [{'stage': 1, 'issues': [
            {'identifier': 'STT-2', 'status': 'todo', 'description': '**Ждёт:** ответа заказчика'},
            {'identifier': 'STT-3', 'status': 'done', 'description': '**Ждёт:** уже не ждёт'},
            {'identifier': 'STT-4', 'status': 'waiting', 'description': '**Ждёт:**'},
            {'identifier': 'STT-5', 'status': 'todo', 'description': 'обычная'}]}], 'unstaged': []}

    def __call__(self, ws):
        def call(*a):
            self.calls.append((ws, a))
            return self.children if a[:2] == ('issue', 'children') else {}
        return call

    def writes(self):
        return [(ws, a) for ws, a in self.calls if a[:2] in (('issue', 'stages'), ('issue', 'update'))]


class EpicsToStages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = self.tmp / 'conveyor.json'
        self.cfg.write_text(json.dumps({'epics': [
            {'key': 'STT-239', 'workspace': 'ws', 'squad_id': 'squad-1', 'repo': '/srv/git/rp.git', 'base': 'main',
             'acceptance': ['make check'], 'acceptance_timeout': 900, 'acceptance_env': {'DB_PASSWORD': 'secret-value'}},
            {'key': 'STT-300', 'workspace': 'ws', 'squad_id': 'squad-1'},
            {'key': 'STT-301', 'workspace': 'ws', 'squad_id': 'squad-1', 'kind': 'issue'},
            {'key': 'STT-302', 'workspace': 'ws', 'squad_id': 'squad-1'}]}))
        self.controls = self.tmp / 'controls.json'
        self.controls.write_text(json.dumps({'targets': {'STT-300': {'paused': True}, 'STT-302': {'enabled': False}}}))
        self.out = []

    def run_it(self, apply):
        m = FakeMultica()
        report = ets.migrate(ets.load_targets(self.cfg, self.controls), m, apply, self.tmp / 'drafts', self.out.append)
        return m, report

    def test_сухой_прогон_ничего_не_пишет(self):
        m, report = self.run_it(False)
        self.assertEqual(m.writes(), [])
        self.assertFalse((self.tmp / 'drafts').exists())
        self.assertIn('STT-239: issue stages --squad squad-1', self.out)

    def test_перенос(self):
        m, report = self.run_it(True)
        self.assertEqual(m.writes(), [
            ('ws', ('issue', 'stages', 'STT-239', '--squad', 'squad-1')),
            ('ws', ('issue', 'update', 'STT-2', '--status', 'waiting')),
            ('ws', ('issue', 'update', 'STT-2', '--status', 'waiting')),  # STT-300 на паузе: стадии нет, ждущие — да
        ])
        draft = json.loads((self.tmp / 'drafts' / 'rp.acceptance.json').read_text())
        self.assertEqual(draft['commands'], ['make check'])
        self.assertEqual(draft['timeout_seconds'], 900)
        self.assertNotIn('secret-value', json.dumps(draft))
        reasons = dict(report)
        self.assertIn('DB_PASSWORD', reasons['STT-239'])
        self.assertIn('паузе', reasons['STT-300'])
        self.assertIn('без стадий', reasons['STT-301'])
        self.assertNotIn('STT-302', reasons)  # выключена в пульте — просто пропуск


class RetireHost(unittest.TestCase):
    UNITS = ['multica-conveyor.timer', 'multica-conveyor.service', 'multica-provider.timer', 'multica-provider.service',
             'multica-fallback.timer', 'multica-fallback.service', 'multica-control.service']

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for f in ['usr/local/bin/multica-conveyor', 'usr/local/bin/mconv', 'usr/local/bin/control_state.py',
                  'usr/local/bin/subs-pick', 'etc/multica-conveyor.json', 'opt/multica-control/control_state.py']:
            (self.root / f).parent.mkdir(parents=True, exist_ok=True)
            (self.root / f).write_text(f)
        for u in self.UNITS:
            (self.root / 'etc/systemd/system').mkdir(parents=True, exist_ok=True)
            (self.root / 'etc/systemd/system' / u).write_text(u)
        self.log = self.root / 'systemctl.log'
        self.enabled = self.root / 'enabled'
        self.enabled.write_text('multica-conveyor.timer\nmulticа-none\nmultica-control.service\n')
        self.systemctl = self.root / 'systemctl'
        self.systemctl.write_text(f'''#!/bin/sh
echo "$*" >> {self.log}
case "$1" in
  is-active) exit 1 ;;
  is-enabled) grep -qx "$3" {self.enabled} ;;
  cat) exit 1 ;;
  *) exit 0 ;;
esac
''')
        self.systemctl.chmod(0o755)

    def retire(self, *args):
        return subprocess.run(['bash', str(HERE / 'retire-host'), *args], capture_output=True, text=True,
                              env={'PATH': '/usr/bin:/bin', 'ROOT': str(self.root), 'SYSTEMCTL': str(self.systemctl)})

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_check_ничего_не_меняет(self):
        r = self.retire('--check')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / 'usr/local/bin/multica-conveyor').exists())
        self.assertNotIn('disable', ' '.join(self.calls()))
        self.assertIn('/usr/local/bin/mconv', r.stdout)

    def test_снятие_и_откат(self):
        r = self.retire()
        self.assertEqual(r.returncode, 0, r.stderr)
        for gone in ['usr/local/bin/multica-conveyor', 'usr/local/bin/mconv', 'etc/multica-conveyor.json',
                     'etc/systemd/system/multica-conveyor.timer', 'etc/systemd/system/multica-provider.service']:
            self.assertFalse((self.root / gone).exists(), gone)
        for kept in ['usr/local/bin/control_state.py', 'usr/local/bin/subs-pick', 'opt/multica-control/control_state.py',
                     'etc/systemd/system/multica-control.service']:
            self.assertTrue((self.root / kept).exists(), kept)
        self.assertIn('disable --now multica-conveyor.timer', self.calls())
        self.assertNotIn('disable --now multica-control.service', self.calls())
        backup = next((self.root / 'var/backups').glob('conveyor-retire.*'))
        rollback = subprocess.run(['bash', str(backup / 'rollback.sh')], capture_output=True, text=True)
        self.assertEqual(rollback.returncode, 0, rollback.stderr)
        self.assertTrue((self.root / 'usr/local/bin/multica-conveyor').exists())
        self.assertEqual((self.root / 'etc/multica-conveyor.json').read_text(), 'etc/multica-conveyor.json')
        self.assertIn('enable --now multica-conveyor.timer', self.calls())

    def test_с_пультом_и_во_время_тика(self):
        r = self.retire('--with-pult')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.root / 'etc/systemd/system/multica-control.service').exists())
        self.assertTrue((self.root / 'opt/multica-control/control_state.py').exists(), 'модуль пульта остаётся для subs-pick')
        self.systemctl.write_text(f'#!/bin/sh\necho "$*" >> {self.log}\n[ "$1" = is-active ] && exit 0\nexit 0\n')
        busy = self.retire()
        self.assertNotEqual(busy.returncode, 0)
        self.assertIn('идёт тик', busy.stderr)


if __name__ == '__main__':
    unittest.main()
