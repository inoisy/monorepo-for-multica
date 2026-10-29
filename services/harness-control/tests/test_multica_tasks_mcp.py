"""Политика и доверенная проверка multica-tasks-mcp: схема, цели, перезапуск, health, отказ на подмене контракта."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import PKG
from harness_control import policy

REPO = PKG.parent.parent
CANDIDATE = REPO / 'mcp' / 'multica-tasks'
CHECK = PKG / 'checks' / 'multica-tasks-mcp' / 'mcp_smoke.py'
POLICY = PKG / 'policy.d' / 'multica-tasks-mcp.json'


def load():
    raw_bytes = POLICY.read_bytes()
    return policy.Policy(json.loads(raw_bytes), raw_bytes, policy.hash_tree(CHECK.parent), 'test')


class MulticaTasksPolicy(unittest.TestCase):
    def test_политика_проходит_строгую_схему(self):
        p = load()
        self.assertEqual(p.name, 'multica-tasks-mcp')
        self.assertEqual(p.source['require_ref'], 'origin/main')

    def test_цели_покрывают_все_файлы_кандидата_и_лежат_в_каталоге_сервиса(self):
        p = load()
        shipped = {t['src'] for t in p.targets}
        on_disk = {'bin/multica-tasks-mcp', *(f'multica_tasks/{f.name}' for f in (CANDIDATE / 'multica_tasks').glob('*.py'))}
        self.assertEqual(shipped, on_disk)
        for t in p.targets:
            self.assertTrue(t['dst'].startswith('/usr/local/lib/multica-tasks-mcp/'), t['dst'])
            self.assertTrue((CANDIDATE / t['src']).is_file(), t['src'])
            self.assertEqual(t['mode'], '0755' if t['src'].startswith('bin/') else '0644')

    def test_перезапуск_юнита_при_смене_любого_файла_и_health_по_loopback(self):
        p = load()
        (restart,) = p.restart_units
        self.assertEqual(restart['unit'], 'multica-tasks-mcp.service')
        self.assertEqual(set(restart['when_changed']), {t['dst'] for t in p.targets})
        self.assertEqual(p.health['http'], [{'url': 'http://127.0.0.1:8101/healthz', 'expect': [200]}])
        self.assertEqual(p.health['units'], [])  # долгоживущий юнит: проверка «запуск после активации» для него не подходит
        self.assertEqual(p.required_units, ['multica-tasks-mcp.service'])

    def test_unit_и_порт_согласованы_с_политикой(self):
        unit = (CANDIDATE / 'systemd' / 'multica-tasks-mcp.service').read_text()
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/lib/multica-tasks-mcp/bin/multica-tasks-mcp', unit)
        self.assertIn('EnvironmentFile=/etc/multica-tasks-mcp/env', unit)
        self.assertIn('8101', (CANDIDATE / 'deploy' / 'Caddyfile.fragment').read_text())

    def test_запуск_юнита_не_от_root(self):
        unit = (CANDIDATE / 'systemd' / 'multica-tasks-mcp.service').read_text()
        self.assertIn('User=multica-mcp', unit)
        self.assertNotRegex(unit, r'(?m)^User=root')

    def test_команда_тестов_видит_достаточно_тестов(self):
        p = load()
        r = subprocess.run([sys.executable, '-I', '-m', 'unittest', 'discover', '-s', 'tests', '-q'], cwd=CANDIDATE,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        import re
        count = int(re.search(p.validate['tests']['count_regex'], r.stderr).group(1))
        self.assertGreaterEqual(count, p.validate['tests']['min'])


class SmokeCheck(unittest.TestCase):
    def run_check(self, work):
        return subprocess.run([sys.executable, '-I', str(CHECK), str(work)], capture_output=True, text=True)

    def candidate_copy(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name) / 'work'
        shutil.copytree(CANDIDATE, work, ignore=shutil.ignore_patterns('__pycache__'))
        return work

    def test_штатный_кандидат_проходит(self):
        r = self.run_check(CANDIDATE)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'mcp-smoke: ok'), r.stderr)

    def test_лишний_инструмент_отклоняется(self):
        work = self.candidate_copy()
        path = work / 'multica_tasks' / 'tools.py'
        path.write_text(path.read_text().replace("TOOLS = {", "TOOLS = {\n    'delete_issue': {'description': 'x', 'write': True, 'inputSchema': {}},"))
        r = self.run_check(work)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('набор инструментов изменился', r.stderr)

    def mutate_policy(self, old, new):
        work = self.candidate_copy()
        path = work / 'multica_tasks' / 'policy.py'
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1))
        return self.run_check(work)

    def test_запрещённая_группа_в_allowlist_отклоняется(self):
        for group in ('daemon', 'auth', 'autopilot', 'repo', 'attachment'):
            with self.subTest(group=group):
                r = self.mutate_policy("('version',): frozenset(),", f"('version',): frozenset(),\n    ('{group}', 'list'): frozenset(),")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('allowlist открывает', r.stderr)

    def test_запись_в_agent_и_skill_в_allowlist_отклоняется(self):
        for pair in ("('agent', 'update')", "('agent', 'delete')", "('skill', 'create')", "('runtime', 'list')"):
            with self.subTest(pair=pair):
                r = self.mutate_policy("('version',): frozenset(),", f"('version',): frozenset(),\n    {pair}: frozenset(),")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('allowlist открывает', r.stderr)

    def test_расширение_workspace_и_subscription_отклоняется(self):
        for pair in ("('workspace', 'get')", "('subscription', 'create')"):
            with self.subTest(pair=pair):
                r = self.mutate_policy("('version',): frozenset(),", f"('version',): frozenset(),\n    {pair}: frozenset(),")
                self.assertNotEqual(r.returncode, 0)

    def test_запуск_через_shell_отклоняется(self):
        work = self.candidate_copy()
        path = work / 'multica_tasks' / 'runner.py'
        path.write_text(path.read_text().replace("start_new_session=True", "start_new_session=True, shell=True"))
        r = self.run_check(work)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('запуск через shell', r.stderr)

    def test_delete_в_коде_отклоняется(self):
        work = self.candidate_copy()
        path = work / 'multica_tasks' / 'service.py'
        path.write_text(path.read_text() + "\nMETHOD = 'DELETE'\n")
        r = self.run_check(work)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('метод DELETE', r.stderr)

    def test_сравнение_ключа_без_compare_digest_отклоняется(self):
        work = self.candidate_copy()
        path = work / 'multica_tasks' / 'http.py'
        path.write_text(path.read_text().replace('hmac.compare_digest', 'operator_eq'))
        r = self.run_check(work)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('compare_digest', r.stderr)


if __name__ == '__main__':
    unittest.main()
