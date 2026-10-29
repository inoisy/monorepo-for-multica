import json
import unittest
from pathlib import Path

from support import ILYA_KEY, ILYA_PAT, KEY, PAT, McpCase
from multica_tasks.config import Client, Config, ConfigError

class Transport(McpCase):
    def setUp(self):
        super().setUp()
        self.start_http()

    def test_без_ключа_и_с_неверным_ключом_401(self):
        self.assertEqual(self.rpc('tools/list', key=None)[0], 401)
        self.assertEqual(self.rpc('tools/list', key='x' * 40)[0], 401)
        self.assertEqual(self.rpc('tools/list', key=KEY[:-1])[0], 401)
        status, _, resp = self.http(body={'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, headers={'Authorization': f'Basic {KEY}'})
        self.assertEqual((status, resp.getheader('WWW-Authenticate')), (401, 'Bearer'))
        self.assertEqual(self.cli.calls, [])

    def test_ключ_сравнивается_через_compare_digest(self):
        import inspect
        from multica_tasks import http
        self.assertIn('hmac.compare_digest', inspect.getsource(http))

    def test_ключ_каждого_клиента_пускает_а_неизвестный_нет(self):
        self.assertEqual(self.rpc('tools/list', key=KEY)[0], 200)
        self.assertEqual(self.rpc('tools/list', key=ILYA_KEY)[0], 200)
        self.assertEqual(self.rpc('tools/list', key=PAT)[0], 401)  # PAT — не ключ входа
        self.assertEqual(self.rpc('tools/list', key=ILYA_KEY + 'x')[0], 401)

    def test_tools_list_ровно_один_инструмент(self):
        status, body = self.rpc('tools/list')
        self.assertEqual(status, 200)
        (tool,) = body['result']['tools']
        self.assertEqual(tool['name'], 'multica')
        self.assertEqual(tool['inputSchema']['required'], ['args'])
        self.assertEqual(set(tool['inputSchema']['properties']), {'args', 'stdin', 'workspace'})

    def test_тело_больше_лимита_413(self):
        self.config = Config(**{**self.config.__dict__, 'max_body': 2048})
        self.start_http()
        status, _, _ = self.http(raw=b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"pad":"' + b'x' * 4000 + b'"}}',
                                 headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
        self.assertEqual(status, 413)

    def test_лимит_по_умолчанию_один_мегабайт(self):
        self.assertEqual(Config(api_url='http://x', clients=()).max_body, 1024 * 1024)

    def test_чужой_origin_403(self):
        self.assertEqual(self.rpc('tools/list', headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.rpc('tools/list', key=None, headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.rpc('tools/list', headers={'Origin': 'https://claude.ai'})[0], 200)

    def test_чужой_host_403(self):
        self.assertEqual(self.rpc('tools/list', headers={'Host': 'evil.example'})[0], 403)

    def test_get_это_405_а_не_сессия(self):
        status, _, resp = self.http('GET', headers={'Authorization': f'Bearer {KEY}'})
        self.assertEqual((status, resp.getheader('Allow')), (405, 'POST'))

    def test_healthz_и_чужие_пути(self):
        self.assertEqual(self.http('GET', '/healthz')[0], 200)
        self.assertEqual(self.http('GET', '/')[0], 404)
        self.assertEqual(self.http('POST', '/mcp/../admin', headers={'Authorization': f'Bearer {KEY}'})[0], 404)

    def test_уведомление_202_без_тела(self):
        status, text, _ = self.http(body={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                                    headers={'Authorization': f'Bearer {KEY}'})
        self.assertEqual((status, text), (202, b''))

    def test_мусорный_json_и_batch(self):
        h = {'Authorization': f'Bearer {KEY}'}
        self.assertEqual(self.http(raw=b'{oops', headers=h)[0], 400)
        self.assertEqual(self.http(raw=b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]', headers=h)[0], 400)
        self.assertEqual(self.http(raw=b'', headers={**h, 'Content-Length': '0'})[0], 400)

    def test_перебор_ключа_упирается_в_429(self):
        codes = [self.rpc('tools/list', key='x' * 40)[0] for _ in range(8)]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(set(codes[5:]), {429})
        self.assertEqual(self.rpc('tools/list')[0], 429)  # окно общее для адреса, даже верный ключ ждёт

    def test_протокол_initialize_ping_и_неизвестный_метод(self):
        _, init = self.rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}})
        self.assertEqual(init['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(init['result']['serverInfo']['name'], 'multica-tasks')
        self.assertEqual(self.rpc('ping')[1]['result'], {})
        self.assertEqual(self.rpc('resources/list')[1]['error']['code'], -32601)

    def test_неподдерживаемая_версия_не_вызывает_инструмент(self):
        call = {'name': 'multica', 'arguments': {'args': ['version']}}
        status, _ = self.rpc('tools/call', call, headers={'MCP-Protocol-Version': '2099-01-01'})
        self.assertEqual(status, 400)
        self.assertEqual(self.cli.calls, [])
        for version in ('2025-03-26', '2025-06-18'):
            self.assertEqual(self.rpc('ping', headers={'MCP-Protocol-Version': version})[0], 200)

    def test_iserror_по_коду_выхода(self):
        good = self.tool(['version'])
        self.assertIs(good['result']['isError'], False)
        self.cli.rule(['issue', 'get'], exit=1, stderr='not found')
        bad = self.tool(['issue', 'get', 'TST-404'])
        self.assertIs(bad['result']['isError'], True)
        self.assertEqual(json.loads(bad['result']['content'][0]['text'])['exit_code'], 1)

    def test_вне_allowlist_это_json_rpc_32602_без_запуска(self):
        body = self.tool(['agent', 'update', 'a'])
        self.assertEqual(body['error']['code'], -32602)
        self.assertIn('только по ssh', body['error']['message'])
        self.assertNotIn('result', body)
        self.assertEqual(self.cli.calls, [])

    def test_неверное_имя_и_форма_вызова_32602(self):
        for name in ([], {}, None, True, 42, ''):
            with self.subTest(name=name):
                status, body = self.rpc('tools/call', {'name': name, 'arguments': {}})
                self.assertEqual((status, body['id'], body['error']['code']), (200, 1, -32602))
        for call in ({'name': 'get_issue', 'arguments': {}}, {'name': 'multica', 'arguments': {'args': 'issue'}},
                     {'name': 'multica'}):
            with self.subTest(call=call):
                self.assertEqual(self.rpc('tools/call', call)[1]['error']['code'], -32602)
        self.assertEqual(self.rpc('ping')[1]['result'], {})
        self.assertEqual(self.cli.calls, [])

    def test_секреты_в_ошибках_аргументов_маскируются(self):
        body = self.tool(['issue', 'get', 'x'], workspace=f'{KEY} {ILYA_PAT}')
        text = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(KEY, text)
        self.assertNotIn(ILYA_PAT, text)

    def test_ip_клиента_из_forwarded_только_с_loopback(self):
        call = {'name': 'multica', 'arguments': {'args': ['version']}}
        # от Caddy (loopback): адрес клиента — последний элемент заголовка
        self.rpc('tools/call', call, headers={'X-Forwarded-For': '1.2.3.4, 160.79.104.5'})
        self.assertEqual(self.audit_lines()[-1]['client_ip'], '160.79.104.5')
        # с чужого адреса заголовок подделать нельзя
        self.rpc('tools/call', call, headers={'X-Forwarded-For': '1.2.3.4'}, peer='198.51.100.7')
        self.assertEqual(self.audit_lines()[-1]['client_ip'], '198.51.100.7')


class Settings(McpCase):
    ENV = {'MULTICA_MCP_KEY': 'k' * 32, 'MULTICA_PAT': 'p', 'MULTICA_API_URL': 'http://127.0.0.1:8080/',
           'MULTICA_MCP_WORKSPACES': 'stt, toons', 'STATE_DIRECTORY': '/var/lib/x'}

    def clients_file(self, rows, mode=0o600):
        path = Path(self.tmp.name) / 'clients.json'
        path.write_text(rows if isinstance(rows, str) else json.dumps(rows, ensure_ascii=False))
        path.chmod(mode)
        return str(path)

    def good_row(self, **extra):
        return {'name': 'Илья', 'key': 'i' * 32, 'token': 'mul_i', **extra}

    def test_полная_конфигурация_по_умолчанию_один_клиент(self):
        c = Config.from_env(self.ENV)
        self.assertEqual((c.api_url, c.port, str(c.state_dir)), ('http://127.0.0.1:8080', 8101, '/var/lib/x'))
        self.assertEqual(c.clients, (Client('Claude (MCP)', 'k' * 32, 'p', ('stt', 'toons')),))
        self.assertEqual(c.host, '127.0.0.1')

    def test_файл_клиентов_добавляется_к_клиенту_по_умолчанию(self):
        path = self.clients_file([self.good_row(workspaces=['stt']), self.good_row(name='Анна', key='a' * 32)])
        c = Config.from_env({**self.ENV, 'MULTICA_MCP_CLIENTS': path})
        self.assertEqual([x.name for x in c.clients], ['Claude (MCP)', 'Илья', 'Анна'])
        self.assertEqual(c.clients[1].workspaces, ('stt',))
        self.assertEqual(c.clients[2].workspaces, ('stt', 'toons'))
        self.assertEqual(set(c.secrets), {'k' * 32, 'p', 'i' * 32, 'mul_i', 'a' * 32})

    def test_только_файл_клиентов_без_общего_ключа(self):
        env = {k: v for k, v in self.ENV.items() if k not in ('MULTICA_MCP_KEY', 'MULTICA_PAT')}
        c = Config.from_env({**env, 'MULTICA_MCP_CLIENTS': self.clients_file([self.good_row()])})
        self.assertEqual([x.name for x in c.clients], ['Илья'])

    def test_отказ_на_старте(self):
        bad = {'без клиентов': {'MULTICA_MCP_KEY': '', 'MULTICA_PAT': ''}, 'короткий ключ': {'MULTICA_MCP_KEY': 'k' * 31},
               'без PAT': {'MULTICA_PAT': ''}, 'без воркспейсов': {'MULTICA_MCP_WORKSPACES': ' , '},
               'адрес с путём': {'MULTICA_API_URL': 'http://x/api'}, 'без каталога': {'STATE_DIRECTORY': ''}}
        for name, patch in bad.items():
            with self.subTest(name), self.assertRaises(ConfigError):
                Config.from_env({**self.ENV, **patch})

    def test_плохой_файл_клиентов_отказ(self):
        cases = {
            'нет файла': '/nonexistent/clients.json', 'не json': self.clients_file('{oops'),
            'не массив': self.clients_file({'a': 1}), 'строка вместо объекта': self.clients_file(['x']),
            'без токена': self.clients_file([{'name': 'a', 'key': 'a' * 32}]),
            'короткий ключ': self.clients_file([self.good_row(key='короткий')]),
            'пустые воркспейсы': self.clients_file([self.good_row(workspaces=[])]),
            'воркспейсы не строки': self.clients_file([self.good_row(workspaces=[1])]),
            'дубль имени': self.clients_file([self.good_row(), self.good_row(key='b' * 32)]),
            'дубль ключа': self.clients_file([self.good_row(), self.good_row(name='Анна')]),
            'ключ как у клиента по умолчанию': self.clients_file([self.good_row(key='k' * 32)]),
            'открыт группе': self.clients_file([self.good_row()], mode=0o640),
            'открыт всем': self.clients_file([self.good_row()], mode=0o644),
        }
        for name, path in cases.items():
            with self.subTest(name), self.assertRaises(ConfigError):
                Config.from_env({**self.ENV, 'MULTICA_MCP_CLIENTS': path})

    def test_ошибки_конфигурации_не_содержат_секретов(self):
        path = self.clients_file([self.good_row(key='короткий', token='mul_СЕКРЕТНЫЙ')])
        with self.assertRaises(ConfigError) as ctx:
            Config.from_env({**self.ENV, 'MULTICA_MCP_CLIENTS': path})
        self.assertNotIn('СЕКРЕТНЫЙ', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
