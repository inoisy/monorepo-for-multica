import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from support import KEY, OTHER_WS, WS, WORKSPACES, McpCase, can_listen_tcp
from multica_tasks.config import Client, Config, ConfigError, load_clients
from multica_tasks.errors import InvalidParams
from multica_tasks.multica_auth import MulticaApi, MulticaAuthError
from multica_tasks.oauth_service import load_key
from multica_tasks.service import Service
from multica_tasks.runner import Runner


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


class Membership(McpCase):
    clients = ()

    def setUp(self):
        super().setUp()
        self.clock = Clock()
        self.service = Service(Runner(self.config), self.audit, clock=self.clock, membership_ttl=30)
        self.anna = Client('Анна', '', 'mul_anna', ('*',), ident='u-anna', source='oauth')

    def run_issue(self, client, workspace):
        return self.service.call_tool('multica', {'args': ['issue', 'list'], 'workspace': workspace}, '', client)

    def listings(self):
        return len([c for c in self.cli.calls if c['argv'][:2] == ['workspace', 'list']])

    def set_workspaces(self, rows):
        self.cli.behavior['workspaces'] = rows
        self.cli.save()

    def test_все_воркспейсы_пользователя_без_списка_в_конфиге(self):
        for ref in ('stt', 'toons', 'hidden', OTHER_WS):
            with self.subTest(ref=ref):
                self.assertFalse(self.run_issue(self.anna, ref)[0])

    def test_воркспейс_без_указания_если_он_единственный(self):
        self.set_workspaces([WORKSPACES[0]])
        self.run_issue(self.anna, None)
        self.assertEqual(self.cli.calls[-1]['env']['MULTICA_WORKSPACE_ID'], WS)
        self.set_workspaces(WORKSPACES)
        self.clock.now += 31
        with self.assertRaises(InvalidParams):
            self.run_issue(self.anna, None)

    def test_новый_воркспейс_виден_со_следующего_вызова_без_перезапуска(self):
        self.set_workspaces([WORKSPACES[0]])
        self.run_issue(self.anna, 'stt')
        with self.assertRaises(InvalidParams):
            self.run_issue(self.anna, 'toons')
        before = self.listings()
        self.set_workspaces(WORKSPACES[:2])
        self.run_issue(self.anna, 'toons')
        self.assertEqual(self.listings() - before, 1, 'промах кэша — ровно одно повторное чтение')
        self.assertEqual(self.cli.calls[-1]['env']['MULTICA_WORKSPACE_ID'], OTHER_WS)

    def test_исключение_из_воркспейса_закрывает_доступ_по_ttl(self):
        self.run_issue(self.anna, 'toons')
        self.set_workspaces([WORKSPACES[0]])
        self.clock.now += 31
        with self.assertRaises(InvalidParams):
            self.run_issue(self.anna, 'toons')
        launched = [c for c in self.cli.calls if c['argv'][:2] == ['issue', 'list']]
        self.assertEqual(len(launched), 1, 'после исключения процесс не запускался')

    def test_попадание_в_кэш_не_читает_список_повторно(self):
        self.run_issue(self.anna, 'stt')
        self.run_issue(self.anna, 'toons')
        self.assertEqual(self.listings(), 1)
        self.clock.now += 31
        self.run_issue(self.anna, 'stt')
        self.assertEqual(self.listings(), 2)

    def test_неизвестный_воркспейс_один_повторный_запрос_и_отказ(self):
        self.run_issue(self.anna, 'stt')
        with self.assertRaises(InvalidParams):
            self.run_issue(self.anna, 'nope')
        self.assertEqual(self.listings(), 2)

    def test_кэш_по_ident_а_не_по_отображаемому_имени(self):
        twin = Client('Анна', '', 'mul_twin', ('*',), ident='u-twin', source='oauth')
        self.run_issue(self.anna, 'stt')
        self.set_workspaces([WORKSPACES[1]])
        with self.assertRaises(InvalidParams):
            self.run_issue(twin, 'stt')
        self.assertEqual(self.run_issue(self.anna, 'stt')[0], False, 'кэш Анны не затронут')
        tokens = [c['env']['MULTICA_TOKEN'] for c in self.cli.calls if c['argv'][:2] == ['workspace', 'list']]
        self.assertEqual(tokens, ['mul_anna', 'mul_twin', 'mul_twin'], 'у двойника свой кэш: промах и одно повторное чтение его токеном')

    def test_явный_список_slug_работает_как_раньше(self):
        limited = Client('Ограниченный', 'x' * 40, 'mul_lim', ('stt',))
        self.assertFalse(self.run_issue(limited, 'stt')[0])
        for ref in ('toons', 'hidden'):
            with self.assertRaises(InvalidParams):
                self.run_issue(limited, ref)

    def test_ключ_со_звёздочкой_видит_все_воркспейсы_владельца_pat(self):
        starred = Client('Все', 'y' * 40, 'mul_all', ('*',))
        self.assertFalse(self.run_issue(starred, 'hidden')[0])
        self.set_workspaces(WORKSPACES + [{'id': 'aaaaaaaa-0000-4000-8000-000000000009', 'name': 'Новый', 'slug': 'fresh'}])
        self.assertFalse(self.run_issue(starred, 'fresh')[0])

    def test_uuid_из_явного_списка_без_запроса_списка(self):
        by_id = Client('X', 'x' * 40, 'mul_x', (WS,))
        self.service.call_tool('multica', {'args': ['issue', 'list']}, '', by_id)
        self.assertEqual(self.listings(), 0)

    def test_аудит_oauth_содержит_пользователя_и_способ(self):
        self.run_issue(self.anna, 'stt')
        entry = self.audit_lines()[-1]
        self.assertEqual((entry['client'], entry['user_id'], entry['auth']), ('Анна', 'u-anna', 'oauth'))
        self.run_issue(Client('Ключ', 'z' * 40, 'mul_z', ('stt',)), 'stt')
        self.assertNotIn('auth', self.audit_lines()[-1])


class ConfigCases(unittest.TestCase):
    def env(self, tmp, **extra):
        return {'MULTICA_API_URL': 'http://127.0.0.1:8080', 'MULTICA_MCP_STATE_DIR': tmp, **extra}

    def keyfile(self, tmp, mode=0o600, content=None):
        from cryptography.fernet import Fernet
        path = Path(tmp) / 'oauth.key'
        path.write_bytes(content or Fernet.generate_key())
        path.chmod(mode)
        return path

    def test_старт_только_с_oauth_без_ключей(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config.from_env(self.env(tmp, MULTICA_MCP_OAUTH_KEY_FILE=str(self.keyfile(tmp))))
            self.assertEqual(config.clients, ())
            self.assertEqual(config.public_url, 'https://multica.yakutov.com')
            self.assertEqual(len(load_key(config.oauth_key_file)), 44)

    def test_без_клиентов_и_oauth_старт_отклоняется(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ConfigError):
            Config.from_env(self.env(tmp))

    def test_ключ_шифрования_права_и_формат(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_key(self.keyfile(tmp, mode=0o644))
            with self.assertRaises(ConfigError):
                load_key(self.keyfile(tmp, content=b'not-a-key'))
            with self.assertRaises(ConfigError):
                load_key(Path(tmp) / 'missing')

    def test_public_url_без_пути(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ConfigError):
            Config.from_env(self.env(tmp, MULTICA_MCP_OAUTH_KEY_FILE='x', MULTICA_MCP_PUBLIC_URL='https://a.example/mcp'))

    def test_звёздочка_в_clients_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clients.json'
            path.write_text(json.dumps([{'name': 'Все', 'key': 'k' * 40, 'token': 'mul_t', 'workspaces': ['*']}]))
            path.chmod(0o600)
            (client,) = load_clients(path, ())
            self.assertTrue(client.any_workspace)
            path.write_text(json.dumps([{'name': 'Все', 'key': 'k' * 40, 'token': 'mul_t', 'workspaces': ['*', 'stt']}]))
            with self.assertRaises(ConfigError):
                load_clients(path, ())


@unittest.skipUnless(can_listen_tcp(), 'в песочнице нет TCP')
class MulticaApiOverHttp(unittest.TestCase):
    """Настоящий HTTP: что именно уходит в Multica (cookie, CSRF, тело) и как разбираются ответы."""

    def setUp(self):
        self.seen = []
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                test.seen.append(('GET', self.path, dict(self.headers), b''))
                if self.path == '/api/redirect':
                    self.send_response(302)
                    self.send_header('Location', 'http://127.0.0.1:1/')
                    self.end_headers()
                    return
                ok = 'multica_auth=GOOD' in self.headers.get('Cookie', '') or self.headers.get('Authorization') == 'Bearer mul_good'
                self.reply(200 if ok else 401, {'id': 'u1', 'name': ' Анна '} if ok else {'error': 'no'})

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                test.seen.append(('POST', self.path, dict(self.headers), body))
                if self.headers.get('X-CSRF-Token') != 'tok':
                    return self.reply(403, {'error': 'CSRF'})
                self.reply(201, {'id': 'p1', 'token': 'mul_new', 'name': 'x'})

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.api = MulticaApi(f'http://127.0.0.1:{self.server.server_port}', timeout=3)

    def test_сессия_передаётся_одной_cookie_без_лишнего(self):
        self.assertEqual(self.api.me_by_session('GOOD').name, 'Анна')
        self.assertEqual(self.seen[0][2]['Cookie'], 'multica_auth=GOOD')

    def test_отказ_и_отсутствие_сессии(self):
        with self.assertRaises(MulticaAuthError) as ctx:
            self.api.me_by_session('BAD')
        self.assertEqual(ctx.exception.kind, 'unauthenticated')
        with self.assertRaises(MulticaAuthError):
            self.api.me_by_session('')

    def test_pat_идёт_заголовком_authorization(self):
        self.assertEqual(self.api.me_by_pat('mul_good').id, 'u1')
        with self.assertRaises(MulticaAuthError):
            self.api.me_by_pat('mul_bad')

    def test_создание_pat_с_csrf_и_телом(self):
        pat = self.api.create_pat('GOOD', 'tok', 'Claude MCP', 90)
        self.assertEqual((pat.id, pat.token), ('p1', 'mul_new'))
        _, path, headers, body = self.seen[-1]
        self.assertEqual((path, headers['X-Csrf-Token'], json.loads(body)), ('/api/tokens', 'tok', {'name': 'Claude MCP', 'expires_in_days': 90}))
        with self.assertRaises(MulticaAuthError) as ctx:
            self.api.create_pat('GOOD', 'wrong', 'x', 90)
        self.assertEqual(ctx.exception.kind, 'unauthenticated')

    def test_редиректы_не_выполняются_и_недоступность_это_unavailable(self):
        with self.assertRaises(MulticaAuthError) as ctx:
            self.api._request('GET', '/api/redirect', {})
        self.assertEqual(ctx.exception.kind, 'unavailable')
        self.assertEqual(len(self.seen), 1)
        dead = MulticaApi('http://127.0.0.1:1', timeout=1)
        with self.assertRaises(MulticaAuthError) as ctx:
            dead.me_by_pat('x')
        self.assertEqual(ctx.exception.kind, 'unavailable')


class CookieParsing(unittest.TestCase):
    def test_разбор_cookie_браузера(self):
        from multica_tasks.multica_auth import session_from_cookie_header as parse
        self.assertEqual(parse('a=1; multica_auth=S; multica_csrf=old; multica_csrf_session=new'), ('S', 'new'))
        self.assertEqual(parse('multica_auth=S; multica_csrf=old'), ('S', 'old'))
        self.assertEqual(parse(''), ('', ''))
        self.assertEqual(parse('мусор;;;='), ('', ''))

    def test_чужие_cookie_с_пробелом_и_кавычками_не_прячут_сессию(self):
        from multica_tasks.multica_auth import session_from_cookie_header as parse
        for header in ('theme={"a": 1}; multica_auth=S; multica_csrf=c', 'a=b c; multica_auth=S; multica_csrf=c',
                       'a="unterminated; multica_auth=S; multica_csrf=c', 'multica_auth="S"; multica_csrf=c'):
            self.assertEqual(parse(header), ('S', 'c'), header)
        self.assertEqual(parse('multica_auth=S; multica_auth=other'), ('S', ''))


if __name__ == '__main__':
    unittest.main()
