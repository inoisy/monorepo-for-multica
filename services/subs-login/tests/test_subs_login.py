"""subs-login: вход в подписки со страницы — поддельный codex, без сети и настоящих учёток."""
import importlib.machinery
import importlib.util
import json
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader('subs_login', str(HERE / 'subs-login'))
spec = importlib.util.spec_from_loader('subs_login', loader)
sl = importlib.util.module_from_spec(spec)
loader.exec_module(sl)

# Fake codex: `login --device-auth` prints a link and a code, then behaves per FAKE_CODEX_MODE;
# `login status` reports by the presence of auth.json in CODEX_HOME.
FAKE_CODEX = r'''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
home = Path(os.environ['CODEX_HOME'])
if sys.argv[1:] == ['login', 'status']:
    auth = home / 'auth.json'
    if auth.exists() and b'revoked' not in auth.read_bytes():
        print('Logged in using ChatGPT'); sys.exit(0)
    print('Not logged in'); sys.exit(1)
print('Open https://auth.example.test/codex/device in your browser', flush=True)
print('Enter code: ABCD-12345', flush=True)
mode = os.environ.get('FAKE_CODEX_MODE', 'ok')
go = Path(os.environ['FAKE_CODEX_GO'])
while not go.exists():
    time.sleep(0.02)
if mode == 'ok':
    (home / 'auth.json').write_text('{"tokens": "NEW-SECRET-TOKEN"}')
    sys.exit(0)
if mode == 'bad_code':
    print('Error: device code rejected', flush=True); sys.exit(1)
while True:
    time.sleep(1)
'''

OLD_AUTH = b'{"tokens": "OLD-SECRET-TOKEN"}'
API_KEY = 'sk-or-v1-PASTED-SECRET-KEY'


def wait_for(cond, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.dir, ignore_errors=True))
        codex = self.dir / 'codex'
        codex.write_text(FAKE_CODEX)
        codex.chmod(0o755)
        self.go = self.dir / 'go'
        os.environ['FAKE_CODEX_GO'] = str(self.go)
        os.environ['FAKE_CODEX_MODE'] = 'ok'
        self.addCleanup(os.environ.pop, 'FAKE_CODEX_GO', None)
        self.addCleanup(os.environ.pop, 'FAKE_CODEX_MODE', None)
        self.auth = self.dir / 'codex-a' / 'auth.json'
        self.auth.parent.mkdir()
        self.auth.write_bytes(OLD_AUTH)
        self.key = self.dir / 'keys' / 'openrouter'
        self.claude = self.dir / 'keys' / 'claude'
        subs = {'tables': {'items': [
            {'id': 'codex-a', 'provider': 'codex', 'auth': 'codex_auth', 'credential': str(self.auth)},
            {'id': 'claude-a', 'provider': 'claude', 'auth': 'claude_oauth', 'credential': str(self.claude)},
            {'id': 'or-a', 'provider': 'openrouter', 'auth': 'api_key', 'credential': str(self.key)},
            {'id': 'no-login', 'provider': 'x', 'auth': 'none', 'credential': '/nowhere'},
        ]}}
        (self.dir / 'subscriptions.json').write_text(json.dumps(subs))
        self.journal_path = self.dir / 'journal.jsonl'
        self.cfg = {**sl.DEFAULTS, 'subs_file': str(self.dir / 'subscriptions.json'), 'journal': str(self.journal_path),
                    'codex': str(codex), 'login_timeout': 30, 'probes': {}}
        self.logins = sl.Logins(self.cfg, sl.journal_writer(self.cfg))

    def account(self, aid):
        return sl.accounts(self.cfg)[aid]

    def journal_text(self):
        return self.journal_path.read_text() if self.journal_path.exists() else ''


class CodexLoginTest(Base):
    def start(self):
        s = self.logins.start_codex('codex-a', self.account('codex-a'), 'owner@example.test')
        self.addCleanup(self.logins._kill, s)
        return s

    def test_success_replaces_file_atomically_with_600(self):
        s = self.start()
        self.assertEqual(s.url, 'https://auth.example.test/codex/device')
        self.assertEqual(s.code, 'ABCD-12345')
        self.assertEqual(self.auth.read_bytes(), OLD_AUTH, 'файл не трогается, пока вход не завершён')
        self.go.touch()
        self.assertTrue(wait_for(lambda: s.state != 'waiting'))
        self.assertEqual(s.state, 'done')
        self.assertEqual(self.auth.read_bytes(), b'{"tokens": "NEW-SECRET-TOKEN"}')
        self.assertEqual(stat.S_IMODE(self.auth.stat().st_mode), 0o600)
        self.assertFalse(Path(s.tmp).exists(), 'временный CODEX_HOME удалён')
        self.assertEqual(sl.login_state(self.cfg, self.account('codex-a')), 'logged_in')

    def assert_untouched(self, s, state):
        self.assertEqual(s.state, state)
        self.assertEqual(self.auth.read_bytes(), OLD_AUTH)
        self.assertFalse(Path(s.tmp).exists())
        self.assertEqual([p.name for p in self.auth.parent.iterdir()], ['auth.json'])

    def test_cancel_keeps_file(self):
        s = self.start()
        self.logins.cancel('codex-a', 'owner@example.test')
        self.go.touch()
        time.sleep(0.2)
        self.assert_untouched(s, 'cancelled')
        self.assertIsNone(self.logins.current('codex-a'))

    def test_timeout_keeps_file(self):
        self.logins.cfg = {**self.cfg, 'login_timeout': 0.5}
        os.environ['FAKE_CODEX_MODE'] = 'hang'
        s = self.start()
        self.go.touch()
        self.assertTrue(wait_for(lambda: s.state != 'waiting'))
        self.assert_untouched(s, 'expired')
        self.assertTrue(wait_for(lambda: s.proc.poll() is not None), 'процесс входа убит')

    def test_wrong_code_keeps_file(self):
        os.environ['FAKE_CODEX_MODE'] = 'bad_code'
        s = self.start()
        self.go.touch()
        self.assertTrue(wait_for(lambda: s.state != 'waiting'))
        self.assert_untouched(s, 'failed')

    def test_second_start_gets_same_window(self):
        first = self.start()
        second = self.logins.start_codex('codex-a', self.account('codex-a'), 'other-owner@example.test')
        self.assertIs(first, second)
        self.assertEqual(first.view()['code'], second.view()['code'])

    def test_journal_has_no_token(self):
        s = self.start()
        self.go.touch()
        self.assertTrue(wait_for(lambda: s.state == 'done'))
        text = self.journal_text()
        self.assertIn('"result": "done"', text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('SECRET', json.dumps(s.view()))

    def test_login_state(self):
        self.assertEqual(sl.login_state(self.cfg, self.account('codex-a')), 'logged_in')
        self.auth.write_text('{"revoked": true}')
        self.assertEqual(sl.login_state(self.cfg, self.account('codex-a')), 'revoked')
        self.auth.unlink()
        self.assertEqual(sl.login_state(self.cfg, self.account('codex-a')), 'never')


    def test_unreadable_credential_is_check_failed(self):
        self.key.parent.mkdir(exist_ok=True)
        self.key.write_text('k')
        self.key.parent.chmod(0o000)
        self.addCleanup(self.key.parent.chmod, 0o755)
        if os.access(self.key.parent, os.X_OK):
            self.skipTest('root reads everything')
        self.assertEqual(sl.login_state(self.cfg, self.account('or-a')), 'check_failed')


class SecretTest(Base):
    def test_claude_token_saved_without_logging_value(self):
        out = self.logins.put_secret('claude-a', self.account('claude-a'), '  sk-ant-oat01-PASTED-SECRET  ', 'o@x')
        self.assertEqual(out['state'], 'done')
        self.assertEqual(self.claude.read_text(), 'sk-ant-oat01-PASTED-SECRET\n')
        self.assertEqual(stat.S_IMODE(self.claude.stat().st_mode), 0o600)
        self.assertNotIn('SECRET', self.journal_text() + json.dumps(out))

    def test_rejected_key_keeps_file(self):
        self.key.parent.mkdir(parents=True, exist_ok=True)
        self.key.write_text('old-key\n')
        self.logins.cfg = {**self.cfg, 'probes': {'openrouter': {'url': 'http://probe'}}}
        orig = sl.probe_key
        sl.probe_key = lambda cfg, provider, key: False
        self.addCleanup(setattr, sl, 'probe_key', orig)
        out = self.logins.put_secret('or-a', self.account('or-a'), API_KEY, 'o@x')
        self.assertEqual(out['state'], 'failed')
        self.assertEqual(self.key.read_text(), 'old-key\n')
        self.assertNotIn('SECRET', self.journal_text() + json.dumps(out))

    def test_bad_value_rejected(self):
        for value in ('', '   ', 'two words', 'x' * 5000):
            self.assertEqual(self.logins.put_secret('claude-a', self.account('claude-a'), value, 'o@x')['state'], 'failed')
        self.assertFalse(self.claude.exists())


class HttpTest(Base):
    ROLES = {'tok-owner': ('u1', 'owner'), 'tok-member': ('u2', 'member')}

    def fake_get(self, cfg, path, headers):
        token = headers.get('Authorization', '').removeprefix('Bearer ')
        if token not in self.ROLES:
            raise sl.urllib.error.HTTPError(path, 401, 'unauthorized', {}, None)
        uid, _ = self.ROLES[token]
        if path == '/api/me':
            return {'id': uid, 'email': f'{uid}@example.test'}
        if path == '/api/workspaces':
            return [{'id': 'ws-1', 'slug': 'stt'}]
        if path == '/api/workspaces/ws-1/members':
            return [{'user_id': u, 'role': r} for u, r in self.ROLES.values()]
        raise AssertionError(path)

    def setUp(self):
        super().setUp()
        handler = sl.make_handler(self.cfg, self.logins, get=self.fake_get)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def call(self, method, path, token=None, body=None, marker=True):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        if marker and method == 'POST':
            headers['X-Subs-Login-Request'] = '1'
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except sl.urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_accounts_for_members(self):
        code, raw = self.call('GET', '/api/accounts?ws=stt', 'tok-member')
        self.assertEqual(code, 200)
        out = json.loads(raw)
        self.assertFalse(out['can_login'])
        self.assertEqual({a['id']: a['state'] for a in out['accounts']},
                         {'codex-a': 'logged_in', 'claude-a': 'never', 'or-a': 'never'})
        self.assertNotIn('SECRET', raw)
        self.assertNotIn('credential', raw, 'пути учёток наружу не отдаются')

    def test_no_session_401(self):
        self.assertEqual(self.call('GET', '/api/accounts?ws=stt')[0], 401)
        self.assertEqual(self.call('GET', '/api/accounts?ws=stt', 'tok-stranger')[0], 401)
        self.assertEqual(self.call('GET', '/api/accounts?ws=other', 'tok-owner')[0], 401)

    def test_not_owner_403_and_file_untouched(self):
        code, _ = self.call('POST', '/api/login?ws=stt', 'tok-member', {'account': 'claude-a', 'action': 'secret', 'value': 'x'})
        self.assertEqual(code, 403)
        self.assertFalse(self.claude.exists())

    def test_post_without_marker_header_403(self):
        code, _ = self.call('POST', '/api/login?ws=stt', 'tok-owner', {'account': 'claude-a', 'action': 'secret', 'value': 'x'},
                            marker=False)
        self.assertEqual(code, 403)
        self.assertFalse(self.claude.exists())

    def test_owner_flow(self):
        code, raw = self.call('POST', '/api/login?ws=stt', 'tok-owner', {'account': 'codex-a', 'action': 'start'})
        self.assertEqual(code, 200)
        first = json.loads(raw)
        self.addCleanup(self.logins.cancel, 'codex-a', 'test')
        self.assertEqual(first['code'], 'ABCD-12345')
        code, raw = self.call('POST', '/api/login?ws=stt', 'tok-owner', {'account': 'codex-a', 'action': 'start'})
        self.assertEqual(json.loads(raw)['session'], first['session'])
        self.go.touch()
        self.assertTrue(wait_for(lambda: json.loads(self.call('GET', '/api/login?ws=stt&account=codex-a', 'tok-member')[1])
                                 ['state'] == 'done'))
        code, raw = self.call('POST', '/api/login?ws=stt', 'tok-owner', {'account': 'or-a', 'action': 'secret', 'value': API_KEY})
        self.assertEqual(json.loads(raw)['state'], 'done')
        self.assertNotIn('SECRET', raw + self.journal_text())

    def test_wrong_action_and_unknown_account(self):
        self.assertEqual(self.call('POST', '/api/login?ws=stt', 'tok-owner', {'account': 'claude-a', 'action': 'start'})[0], 400)
        self.assertEqual(self.call('POST', '/api/login?ws=stt', 'tok-owner', {'account': 'no-login', 'action': 'start'})[0], 404)


if __name__ == '__main__':
    unittest.main()
