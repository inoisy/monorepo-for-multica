import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from support import PKG

BOOT = PKG / 'bootstrap'
VISUDO = shutil.which('visudo') or '/usr/sbin/visudo'
PLAN = re.compile(r'^\s+install (?:-D )?(?:-d )?-o (\S+) -g (\S+) -m (\d{4}) (.+)$')


def check_output():
    r = subprocess.run(['bash', str(BOOT / 'install.sh'), '--check'], capture_output=True, text=True, timeout=120,
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'})
    return r


def tree_state(path):
    return sorted((str(p.relative_to(path)), p.stat().st_size, p.stat().st_mtime_ns) for p in Path(path).rglob('*') if p.is_file())


class Scripts(unittest.TestCase):
    def test_синтаксис_bash(self):
        for script in sorted(BOOT.glob('*.sh')):
            with self.subTest(script.name):
                self.assertEqual(subprocess.run(['bash', '-n', str(script)], capture_output=True).returncode, 0)

    @unittest.skipUnless(os.path.exists(VISUDO), 'нет visudo')
    def test_sudoers_проходит_visudo(self):
        r = subprocess.run([VISUDO, '-cf', str(BOOT / 'sudoers.harness-control')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_sudoers_даёт_только_нужные_глаголы_только_agents(self):
        rules = [l for l in (BOOT / 'sudoers.harness-control').read_text().splitlines() if l.strip() and not l.startswith('#')]
        grants = [l for l in rules if 'NOPASSWD' in l]
        self.assertTrue(grants)
        verbs = set()
        for line in grants:
            self.assertRegex(line, r'^agents ALL=\(root\) NOPASSWD: ')
            for cmd in line.split('NOPASSWD:')[1].split(','):
                cmd = cmd.strip()
                self.assertTrue(cmd.startswith('/usr/local/sbin/harness-priv '), cmd)
                verbs.add(cmd.split()[1])
        self.assertEqual(verbs, {'inspect', 'validate', 'deploy', 'rollback', 'op', 'log', 'ops'})
        self.assertFalse({'adopt-baseline', 'recover', 'run-op'} & verbs)
        self.assertNotIn('ALL=(ALL)', ' '.join(rules))
        # Defaults только для harness-priv: остальные правила sudo агента (stand, bio-*) не меняются
        defaults = [l for l in rules if l.startswith('Defaults')]
        self.assertTrue(defaults)
        for line in defaults:
            self.assertTrue(line.startswith('Defaults!/usr/local/sbin/harness-priv '), line)

    def test_юниты_проходят_systemd_analyze(self):
        if not shutil.which('systemd-analyze'):
            self.skipTest('нет systemd-analyze')
        units = [str(p) for p in sorted(BOOT.glob('*.service')) + sorted(BOOT.glob('*.timer'))]
        r = subprocess.run(['systemd-analyze', 'verify', *units], capture_output=True, text=True)
        # исполняемых файлов ещё нет на этой машине — это единственное допустимое замечание
        problems = [l for l in r.stderr.splitlines() if l.strip() and 'is not executable: No such file' not in l
                    and 'Special user nobody' not in l and not l.startswith('/etc/systemd/system/')]
        self.assertEqual(problems, [], r.stderr)

    def test_обновление_снимает_снятые_компоненты(self):
        text = (BOOT / 'install.sh').read_text()
        self.assertIn('for stale in multica-conveyor control-state', text)
        self.assertIn('COMPONENTS=(harness-canary)', text)
        self.assertNotIn('multica-provider', text)
        self.assertEqual(sorted(p.stem for p in (PKG / 'policy.d').glob('*.json')), ['harness-canary', 'multica-tasks-mcp'])
        self.assertFalse((PKG / 'checks' / 'control-state').exists())

    def test_таймер_canary_ставится_выключенным(self):
        plan = check_output().stdout
        self.assertNotRegex(plan, r'enable[^\n]*harness-canary')
        self.assertIn('harness-canary.timer ставится выключенным', plan)


class CheckMode(unittest.TestCase):
    def test_check_без_root_печатает_план_и_sha_и_ничего_не_меняет(self):
        if os.geteuid() == 0:
            self.skipTest('проверка рассчитана на запуск без root')
        before = tree_state(PKG.parent)
        installed = Path('/usr/local/lib/harness-control')
        installed_before = tree_state(installed) if installed.exists() else None
        r = check_output()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r'SHA256 пакета: [0-9a-f]{64}')
        self.assertIn('план:', r.stdout)
        self.assertIn('/etc/sudoers.d/harness-control', r.stdout)
        self.assertEqual(tree_state(PKG.parent), before)
        self.assertEqual(tree_state(installed) if installed.exists() else None, installed_before)

    def test_sha_стабилен(self):
        sha = lambda: re.search(r'SHA256 пакета: (\w+)', check_output().stdout).group(1)
        self.assertEqual(sha(), sha())

    def test_установка_без_root_отказывает_до_изменений(self):
        if os.geteuid() == 0:
            self.skipTest('проверка рассчитана на запуск без root')
        r = subprocess.run(['bash', str(BOOT / 'install.sh')], capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Нужен root', r.stderr)
        self.assertNotIn('install -d', r.stdout.split('план:')[-1])


class Permissions(unittest.TestCase):
    """Агент (uid agents) не должен мочь изменить политику, sudoers, код и чек-лист: всё ставится root:root без записи другим."""

    def setUp(self):
        self.entries = []
        for line in check_output().stdout.splitlines():
            m = PLAN.match(line)
            if m:
                self.entries.append({'owner': m.group(1), 'group': m.group(2), 'mode': int(m.group(3), 8), 'rest': m.group(4)})

    def test_всё_ставится_от_root_без_записи_группе_и_всем(self):
        self.assertGreater(len(self.entries), 30)
        for e in self.entries:
            self.assertEqual((e['owner'], e['group']), ('root', 'root'), e['rest'])
            self.assertEqual(e['mode'] & 0o022, 0, e['rest'])

    def test_sudoers_0440_и_ставится_последним(self):
        last = self.entries[-1]
        self.assertTrue(last['rest'].endswith('/etc/sudoers.d/harness-control'), last)
        self.assertEqual(last['mode'], 0o440)

    def test_политика_и_состояние(self):
        policy = [e for e in self.entries if e['rest'].split()[-1].startswith('/etc/harness-control/')]
        self.assertTrue(policy)
        self.assertTrue(all(e['mode'] in (0o644, 0o755) for e in policy))
        state = [e for e in self.entries if e['rest'].split()[-1] == '/var/lib/harness-control']
        self.assertEqual([e['mode'] for e in state], [0o700])

    def test_harness_priv_ставится_в_sbin_исполняемым_только_root_пишет(self):
        entry = [e for e in self.entries if e['rest'].split()[-1] == '/usr/local/sbin/harness-priv'][0]
        self.assertEqual(entry['mode'], 0o755)


if __name__ == '__main__':
    unittest.main()
