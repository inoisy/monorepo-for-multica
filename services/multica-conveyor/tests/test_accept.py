import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_conveyor import c, sh

SERVICE = Path(__file__).resolve().parent.parent


class AcceptLog(unittest.TestCase):
    """Приёмка на настоящем временном git-репозитории: лог, окружение, таймаут."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(self.tmp)])
        self.repo = self.tmp / 'service'
        self.repo.mkdir()
        for cmd in (['git', 'init', '-q', '-b', 'main'], ['git', 'config', 'user.email', 't@t'], ['git', 'config', 'user.name', 't']):
            sh(self.repo, *cmd)
        (self.repo / 'a.txt').write_text('a\n')
        sh(self.repo, 'git', 'add', 'a.txt')
        sh(self.repo, 'git', 'commit', '-qm', 'init')
        sh(self.repo, 'git', 'switch', '-qc', 't-1-x')
        (self.repo / 'x.ts').write_text('export const x = 1\n')
        sh(self.repo, 'git', 'add', 'x.ts')
        sh(self.repo, 'git', 'commit', '-qm', 'x')
        sh(self.repo, 'git', 'switch', '-q', 'main')
        self.sha = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 't-1-x'], capture_output=True, text=True).stdout.strip()
        state = self.tmp / 'state' / 'state.json'
        p = patch.object(c, 'STATE', state)
        p.start()
        self.addCleanup(p.stop)
        self.r = c.Repo(str(self.repo), 'main')

    def log_file(self):
        return self.tmp / 'state' / 'accept' / f'STT-1-{self.sha[:12]}.log'

    def test_полный_лог_пишется_и_токены_скрыты(self):
        cmds = ['echo "шаг один"', 'echo token=ghp_abcdefghijklmnopqrstuv; echo "$CONFIG_VALUE"; seq 1 500; false']
        ok, why, tail = self.r.accept('t-1-x', cmds, 60, key='STT-1', env={'CONFIG_VALUE': 'hunter2-value'})
        self.assertFalse(ok)
        log = self.log_file().read_text()
        self.assertIn('шаг один', log)
        self.assertIn('\n1\n', log)  # лог полный, а не хвост
        self.assertIn('\n500\n', log)
        for leaked in ('ghp_abcdefghijklmnopqrstuv', 'hunter2-value'):
            self.assertNotIn(leaked, log)
            self.assertNotIn(leaked, tail)
        self.assertIn(str(self.log_file()), tail)
        self.assertEqual(stat.S_IMODE(self.log_file().stat().st_mode), 0o600)

    def test_зелёная_приёмка_тоже_оставляет_лог(self):
        ok, _, _ = self.r.accept('t-1-x', ['echo зелёно-по-логу'], 60, key='STT-1')
        self.assertTrue(ok)
        self.assertIn('зелёно-по-логу', self.log_file().read_text())

    def test_path_и_env_берутся_из_конфига(self):
        tools = self.tmp / 'tools'
        tools.mkdir()
        tool = tools / 'only-here'
        tool.write_text('#!/bin/sh\necho tool-ok\n')
        tool.chmod(0o755)
        path = f'{tools}:/usr/bin:/bin'
        ok, why, _ = self.r.accept('t-1-x', ['only-here', 'test "$MARKER" = on', 'test "$PATH" = "' + path + '"'], 60,
                                   key='STT-1', path=path, env={'MARKER': 'on'})
        self.assertTrue(ok, why)
        header = self.log_file().read_text().splitlines()[0]
        self.assertIn(path, header)
        self.assertIn("'MARKER'", header)
        self.assertNotIn('=on', header)
        ok, why, _ = self.r.accept('t-1-x', ['only-here'], 60, key='STT-1', path='/usr/bin:/bin')
        self.assertFalse(ok)
        self.assertIn('`only-here`', why)

    def test_таймаут_убивает_всю_группу_процессов(self):
        pidfile = self.tmp / 'child.pid'
        cmd = f'sh -c \'trap "" TERM; echo $$ > {pidfile}; sleep 300\' & wait'
        with patch.object(c, 'KILL_GRACE', 1):
            started = time.monotonic()
            ok, why, _ = self.r.accept('t-1-x', [cmd], 2, key='STT-1')
        self.assertFalse(ok)
        self.assertIn('таймаут 2 с', why)
        self.assertLess(time.monotonic() - started, 30)
        pid = int(pidfile.read_text())
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
            self.fail('потомок команды пережил таймаут')
        self.assertIn('таймаут', self.log_file().read_text())

    def test_старые_логи_удаляются(self):
        directory = self.tmp / 'state' / 'accept'
        directory.mkdir(parents=True)
        old, fresh = directory / 'old.log', directory / 'fresh.log'
        old.write_text('x')
        fresh.write_text('x')
        past = time.time() - (c.ACCEPT_LOG_KEEP_DAYS + 1) * 86400
        os.utime(old, (past, past))
        c.prune_accept_logs(directory)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())


class Redact(unittest.TestCase):
    def test_виды_секретов(self):
        text = '\n'.join([
            'API_KEY=abcdef123456', 'password: "s3cret pass"', 'Authorization: Bearer abcdefghijkl123',
            'git clone https://user:pw1234@host/repo.git', 'npm_abcdefghijklmnop', 'eyJhbGciOiJI.eyJzdWIiOiIx.abcd1234',
        ])
        out = c.redact(text)
        for leaked in ('abcdef123456', 's3cret pass', 'abcdefghijkl123', 'pw1234', 'npm_abcdefghijklmnop', 'eyJzdWIiOiIx'):
            self.assertNotIn(leaked, out)
        self.assertIn('git clone', out)

    def test_обычный_текст_не_портится(self):
        text = 'pnpm check: 12 passed, tokens=0 files'
        self.assertEqual(c.redact(text), 'pnpm check: 12 passed, tokens=[скрыто] files')

    def test_значения_из_конфига_вырезаются_дословно(self):
        self.assertEqual(c.redact('prefix zzzzzzzz suffix', ['zzzzzzzz']), f'prefix {c.REDACTED} suffix')


class Capabilities(unittest.TestCase):
    def test_capabilities_печатает_json_без_конфига(self):
        env = {k: v for k, v in os.environ.items() if k != 'MULTICA_CONVEYOR_CONFIG'}
        env['MULTICA_CONVEYOR_CONFIG'] = '/nonexistent/config.json'
        r = subprocess.run([sys.executable, '-I', str(SERVICE / 'multica-conveyor'), '--capabilities'],
                           capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        caps = json.loads(r.stdout)
        self.assertEqual(caps['lanes'], ['epics', 'providers'])
        self.assertIn('accept-log', caps['features'])


if __name__ == '__main__':
    unittest.main()
