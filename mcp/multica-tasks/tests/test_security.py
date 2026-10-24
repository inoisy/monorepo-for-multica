import json
import os
import stat
import unittest

from support import AGENT_A, FORBIDDEN_PATHS, KEY, PAT, SECRET_FIELDS, WS, McpCase
from multica_tasks import api, tools
from multica_tasks.config import Config, ConfigError
from multica_tasks.errors import ForbiddenCall

ALL_TOOL_CALLS = (
    ('list_workspaces', {}), ('list_agents', {'workspace': 'stt'}), ('list_issues', {'workspace': 'stt'}),
    ('list_issues', {'workspace': 'stt', 'stale_minutes': 1}), ('get_issue', {'workspace': 'stt', 'issue': 'TST-1'}),
    ('list_agent_tasks', {'workspace': 'stt', 'agent': 'Бэкенд'}),
    ('comment_issue', {'workspace': 'stt', 'issue': 'TST-1', 'text': 'x'}),
    ('comment_issue', {'workspace': 'stt', 'issue': 'TST-1', 'text': 'x', 'wake': True}),
    ('update_issue', {'workspace': 'stt', 'issue': 'TST-1', 'status': 'todo', 'assignee': 'Тестировщик'}),
    ('wake_issue', {'workspace': 'stt', 'issue': 'TST-1'}),
)


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
        self.assertEqual(self.fake.requests, [])

    def test_ключ_сравнивается_через_compare_digest(self):
        import inspect
        from multica_tasks import http
        self.assertIn('hmac.compare_digest', inspect.getsource(http))

    def test_верный_ключ_отвечает(self):
        status, body = self.rpc('tools/list')
        self.assertEqual(status, 200)
        self.assertEqual(len(body['result']['tools']), 9)

    def test_тело_больше_лимита_413(self):
        status, _, _ = self.http(raw=b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"pad":"' + b'x' * 4000 + b'"}}',
                                 headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
        self.assertEqual(status, 413)

    def test_лимит_по_умолчанию_один_мегабайт(self):
        self.assertEqual(Config(api_url='http://x').max_body, 1024 * 1024)

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

    def test_iserror_только_при_ошибке(self):
        good = self.tool('list_workspaces')
        self.assertIs(good['isError'], False)
        bad = self.tool('get_issue', workspace='stt', issue='TST-404')
        self.assertIs(bad['isError'], True)
        self.assertEqual(json.loads(bad['content'][0]['text'])['error']['code'], 'api_404')
        # тело успешного ответа с ключом «error» внутри (например, ошибка в данных рана) не делает ответ ошибкой
        iid = self.fake.add_issue('TST-70', 'x')
        self.fake.add_task(iid, AGENT_A, 'failed')
        self.fake.tasks[-1]['error'] = 'упал'
        self.assertIs(self.tool('get_issue', workspace='stt', issue='TST-70')['isError'], False)

    def test_секреты_в_ошибках_рана_маскируются_до_обрезки(self):
        from multica_tasks.projection import ERROR_LIMIT
        iid = self.fake.find_issue('TST-1')['id']
        self.fake.add_task(iid, AGENT_A, 'failed')
        for text in (f'сбой: {PAT}, {KEY}', 'x' * (ERROR_LIMIT - 20) + PAT + KEY,
                     'x' * (ERROR_LIMIT - 20) + KEY + PAT):
            self.fake.tasks[-1]['error'] = text
            for name, args, field in (('get_issue', {'issue': 'TST-1'}, 'runs'),
                                      ('list_agent_tasks', {'agent': AGENT_A}, 'tasks')):
                with self.subTest(name=name, text_length=len(text)):
                    result = self.tool(name, workspace='stt', **args)
                    self.assertIs(result['isError'], False)
                    error = json.loads(result['content'][0]['text'])[field][0]['error']
                    self.assertIn('[redacted]', error)
                    self.assertNotIn(PAT[:20], error)
                    self.assertNotIn(KEY[:20], error)
                    self.assertLessEqual(len(error), ERROR_LIMIT + 1)

    def test_секреты_маскируются_в_тексте_ответов_и_ошибках_аргументов(self):
        issue = self.fake.find_issue('TST-1')
        issue['description'] = f'Описание {KEY} {PAT}'
        self.fake.comments[issue['id']] = [{'content': f'Комментарий {KEY} {PAT}'}]
        for name, args, is_error in (('get_issue', {'workspace': 'stt', 'issue': 'TST-1'}, False),
                                     ('list_agents', {'workspace': f'{KEY} {PAT}'}, True),
                                     (f'unknown_{KEY}_{PAT}', {}, True)):
            with self.subTest(name=name):
                result = self.tool(name, **args)
                self.assertIs(result['isError'], is_error)
                payload = json.loads(result['content'][0]['text'])
                text = json.dumps(payload, ensure_ascii=False)
                self.assertIn('[redacted]', text)
                self.assertNotIn(KEY, text)
                self.assertNotIn(PAT, text)

    def test_неверное_имя_инструмента_даёт_json_rpc_ошибку(self):
        for name in ([], {}, None, True, 42, ''):
            with self.subTest(name=name):
                status, body = self.rpc('tools/call', {'name': name, 'arguments': {}})
                self.assertEqual(status, 200)
                self.assertEqual(body['id'], 1)
                self.assertEqual(body['error']['code'], -32602)
                self.assertEqual(self.rpc('ping')[1]['result'], {})
        self.assertEqual(self.fake.requests, [])

    def test_ip_клиента_из_forwarded_только_с_loopback(self):
        call = {'name': 'wake_issue', 'arguments': {'workspace': 'stt', 'issue': 'TST-1'}}
        # от Caddy (loopback): адрес клиента — последний элемент заголовка
        self.rpc('tools/call', call, headers={'X-Forwarded-For': '1.2.3.4, 160.79.104.5'})
        self.assertEqual(self.audit_lines()[-1]['client_ip'], '160.79.104.5')
        # с чужого адреса заголовок подделать нельзя
        self.rpc('tools/call', call, headers={'X-Forwarded-For': '1.2.3.4'}, peer='198.51.100.7')
        self.assertEqual(self.audit_lines()[-1]['client_ip'], '198.51.100.7')


class Whitelist(McpCase):
    def test_запрещённые_пары_отвергаются_клиентом(self):
        client = api.Api('http://127.0.0.1:1', PAT)
        uid = AGENT_A
        for method, path in (('DELETE', f'/api/issues/{uid}'), ('DELETE', f'/api/agents/{uid}'), ('PUT', f'/api/agents/{uid}'),
                             ('PATCH', f'/api/agents/{uid}'), ('POST', '/api/tokens'), ('GET', '/api/tokens'),
                             ('GET', '/mcp-servers'), ('POST', f'/api/agents/{uid}/skills'), ('GET', f'/api/agents/{uid}/env'),
                             ('PUT', f'/api/agents/{uid}/env'), ('POST', f'/api/workspaces/{WS}'), ('DELETE', f'/api/workspaces/{WS}'),
                             ('GET', '/api/issues/TST-1/../../tokens'), ('POST', f'/api/agents/{uid}/cancel-tasks'),
                             ('GET', '/api/issues?x=1'), ('GET', 'http://evil.example/api/issues')):
            with self.subTest(method=method, path=path), self.assertRaises(ForbiddenCall):
                client.request(method, path)

    def test_все_инструменты_ходят_только_по_белому_списку(self):
        self.fake.add_task(self.fake.add_issue('TST-80', 'x', assignee=('agent', AGENT_A)), AGENT_A, 'running')
        for name, args in ALL_TOOL_CALLS:
            self.call(name, **args)
        tid = self.fake.tasks[0]['id']
        self.call('cancel_task', workspace='stt', task_id=tid)
        self.assertTrue(self.fake.requests)
        for r in self.fake.requests:
            with self.subTest(method=r['method'], path=r['path']):
                self.assertTrue(api.is_allowed(r['method'], r['path']))
                self.assertNotEqual(r['method'], 'DELETE')
                self.assertFalse(any(p.search(r['path']) for p in FORBIDDEN_PATHS), r['path'])

    def test_put_только_по_задаче_и_с_разрешёнными_полями(self):
        self.call('update_issue', workspace='stt', issue='TST-1', status='review', assignee='Сквад')
        puts = [r for r in self.fake.requests if r['method'] == 'PUT']
        self.assertEqual(len(puts), 1)
        self.assertRegex(puts[0]['path'], r'^/api/issues/[0-9a-f-]{36}$')
        self.assertLessEqual(set(puts[0]['body']), {'status', 'assignee_type', 'assignee_id', 'suppress_run'})

    def test_pat_идёт_только_в_заголовке_и_воркспейс_в_x_workspace_id(self):
        self.ok('list_agents', workspace='stt')
        for r in self.fake.requests:
            self.assertEqual(r['headers']['Authorization'], f'Bearer {PAT}')
        self.assertEqual(self.fake.requests[-1]['headers']['X-Workspace-Id'], WS)

    def test_редирект_с_токеном_не_выполняется(self):
        import urllib.request
        client = api.Api('http://127.0.0.1:1', PAT)
        redirect = next(h for h in client._opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
        req = urllib.request.Request('http://127.0.0.1:1/api/agents', headers={'Authorization': f'Bearer {PAT}'})
        self.assertIsNone(redirect.redirect_request(req, None, 302, 'Found', {}, 'http://evil.example/steal'))


class Projection(McpCase):
    def test_в_ответах_нет_секретов_агентов_и_лишних_полей(self):
        iid = self.fake.add_issue('TST-90', 'x', assignee=('agent', AGENT_A))
        self.fake.add_task(iid, AGENT_A, 'running')
        outputs = [self.ok(n, **a) for n, a in ALL_TOOL_CALLS[:6]]
        text = json.dumps(outputs, ensure_ascii=False)
        for secret in ('ПРОМПТ-СЕКРЕТ', 'ENV-СЕКРЕТ', 'MCP-СЕКРЕТ', 'ARGS-СЕКРЕТ', 'TOKEN-СЕКРЕТ', 'СКВАД-СЕКРЕТ',
                       '/srv/секрет', 'files.invalid'):
            self.assertNotIn(secret, text)
        for key in list(SECRET_FIELDS) + ['work_dir', 'result', 'attachments']:
            self.assertNotIn(f'"{key}"', text)
        agents = self.ok('list_agents', workspace='stt')['agents']
        self.assertEqual(set(agents[0]), {'id', 'name', 'status', 'visibility', 'max_concurrent_tasks', 'archived_at',
                                          'description', 'active_tasks'})
        self.assertEqual([t['status'] for a in agents for t in a['active_tasks']], ['running'])


class Audit(McpCase):
    def test_каждая_запись_в_аудите_с_нужными_полями(self):
        text = 'секретный комментарий ' + 'я' * 300
        self.ok('comment_issue', workspace='stt', issue='TST-1', text=text)
        self.ok('wake_issue', workspace='stt', issue='TST-1')
        self.ok('update_issue', workspace='stt', issue='TST-1', status='review')
        task = self.fake.tasks[0]['id']
        self.ok('cancel_task', workspace='stt', task_id=task)
        self.err('wake_issue', workspace='hidden', issue='TST-1')
        lines = self.audit_lines()
        self.assertEqual([l['tool'] for l in lines], ['comment_issue', 'wake_issue', 'update_issue', 'cancel_task', 'wake_issue'])
        comment = lines[0]
        self.assertEqual(set(comment), {'time', 'tool', 'workspace', 'issue', 'args', 'result', 'task_id', 'client_ip'})
        self.assertEqual(comment['workspace'], 'stt')
        self.assertEqual(comment['issue'], 'TST-1')
        self.assertEqual(comment['client_ip'], '203.0.113.9')
        self.assertEqual(len(comment['args']['text']['head']), 200)
        self.assertEqual(len(comment['args']['text']['sha256']), 64)
        self.assertNotIn(text, json.dumps(comment, ensure_ascii=False))
        self.assertEqual(lines[1]['task_id'], self.fake.tasks[0]['id'])
        self.assertEqual(lines[3]['task_id'], task)
        self.assertEqual(lines[4]['result']['ok'], False)
        self.assertEqual(lines[4]['result']['code'], 'forbidden_workspace')

    def test_чтение_не_пишет_в_аудит(self):
        self.ok('list_agents', workspace='stt')
        self.ok('get_issue', workspace='stt', issue='TST-1')
        self.assertEqual(self.audit_lines(), [])

    def test_права_файла_0600(self):
        self.ok('wake_issue', workspace='stt', issue='TST-1')
        mode = stat.S_IMODE(os.stat(self.state / 'audit.jsonl').st_mode)
        self.assertEqual(mode, 0o600)

    def test_ключ_и_pat_в_аудит_не_попадают(self):
        self.ok('comment_issue', workspace='stt', issue='TST-1', text=f'вот PAT {PAT} и ключ {KEY}')
        self.err('wake_issue', workspace=f'{PAT}', issue='TST-1')
        raw = (self.state / 'audit.jsonl').read_text()
        self.assertNotIn(PAT, raw)
        self.assertNotIn(KEY, raw)
        self.assertIn('[redacted]', raw)

    def test_ключ_и_pat_не_утекают_в_ответы_и_ошибки(self):
        self.fake.fail[('GET', '/api/agents')] = (500, {'error': f'внутри {PAT}'})
        error = self.err('list_agents', workspace='stt')
        self.assertNotIn(PAT, json.dumps(error))
        self.opener.down = True
        self.service._workspaces = None
        self.assertNotIn(PAT, json.dumps(self.err('list_workspaces')))

    def test_существующий_аудит_дописывается(self):
        self.ok('wake_issue', workspace='stt', issue='TST-1')
        from multica_tasks.audit import AuditLog
        AuditLog(self.state / 'audit.jsonl').write(tool='x')
        self.assertEqual(len(self.audit_lines()), 2)


class Settings(McpCase):
    ENV = {'MULTICA_MCP_KEY': 'k' * 32, 'MULTICA_PAT': 'p', 'MULTICA_API_URL': 'http://127.0.0.1:8080/',
           'MULTICA_MCP_WORKSPACES': 'stt, toons', 'STATE_DIRECTORY': '/var/lib/x'}

    def test_полная_конфигурация(self):
        c = Config.from_env(self.ENV)
        self.assertEqual((c.api_url, c.workspaces, c.port, str(c.state_dir)), ('http://127.0.0.1:8080', ('stt', 'toons'), 8101, '/var/lib/x'))
        self.assertEqual(c.host, '127.0.0.1')

    def test_отказ_на_старте(self):
        bad = {'без ключа': {'MULTICA_MCP_KEY': ''}, 'короткий ключ': {'MULTICA_MCP_KEY': 'k' * 31},
               'без PAT': {'MULTICA_PAT': ''}, 'без воркспейсов': {'MULTICA_MCP_WORKSPACES': ' , '},
               'адрес с путём': {'MULTICA_API_URL': 'http://x/api'}, 'без каталога': {'STATE_DIRECTORY': ''}}
        for name, patch in bad.items():
            with self.subTest(name), self.assertRaises(ConfigError):
                Config.from_env({**self.ENV, **patch})


if __name__ == '__main__':
    unittest.main()
