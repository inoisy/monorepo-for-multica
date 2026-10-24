"""Общие подставки тестов: фейковый Multica API по HTTP и сервер MCP на свободном порту. Реальной сети и LLM нет."""
import http.client
import io
import json
import re
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))

from multica_tasks.api import Api  # noqa: E402
from multica_tasks.audit import AuditLog  # noqa: E402
from multica_tasks.config import Config  # noqa: E402
from multica_tasks.http import AuthLimiter, make_handler  # noqa: E402
from multica_tasks.service import Service  # noqa: E402

KEY = 'k' * 40
PAT = 'mul_secret_pat_' + 'p' * 24
WS = 'aaaaaaaa-0000-4000-8000-000000000001'
OTHER_WS = 'aaaaaaaa-0000-4000-8000-000000000002'
HIDDEN_WS = 'aaaaaaaa-0000-4000-8000-000000000003'
AGENT_A = 'bbbbbbbb-0000-4000-8000-00000000000a'
AGENT_B = 'bbbbbbbb-0000-4000-8000-00000000000b'
LEADER = 'bbbbbbbb-0000-4000-8000-00000000000c'
SQUAD = 'cccccccc-0000-4000-8000-000000000001'
SECRET_FIELDS = {'instructions': 'ПРОМПТ-СЕКРЕТ', 'custom_env': {'TOKEN': 'ENV-СЕКРЕТ'}, 'mcp_config': {'x': 'MCP-СЕКРЕТ'},
                 'custom_args': ['ARGS-СЕКРЕТ'], 'token': 'TOKEN-СЕКРЕТ'}
FORBIDDEN_PATHS = (re.compile(r'^/api/tokens'), re.compile(r'^/mcp-servers'), re.compile(r'^/skills'),
                   re.compile(r'/env(/|$)'), re.compile(r'^/api/agents/[^/]+$'))
ISO = '%Y-%m-%dT%H:%M:%SZ'


def iso(clock, minutes_ago=0):
    import time
    return time.strftime(ISO, time.gmtime(clock - minutes_ago * 60))


class FakeMultica:
    """Минимум поведения Multica: задачи, раны, снимок ранов, rerun, cancel. Все запросы пишутся в self.requests."""

    def __init__(self, now):
        self.now = now
        self.requests = []
        self.lock = threading.Lock()
        self.workspaces = [{'id': WS, 'name': 'stt', 'slug': 'stt'}, {'id': OTHER_WS, 'name': 'Мульты', 'slug': 'toons'},
                           {'id': HIDDEN_WS, 'name': 'Скрытый', 'slug': 'hidden'}]
        self.agents = [
            {'id': AGENT_A, 'name': 'Бэкенд', 'description': 'Бэкенд-разработчик', 'status': 'idle', 'visibility': 'workspace',
             'archived_at': None, 'max_concurrent_tasks': 2, **SECRET_FIELDS},
            {'id': AGENT_B, 'name': 'Тестировщик', 'description': 'QA', 'status': 'idle', 'visibility': 'workspace',
             'archived_at': None, 'max_concurrent_tasks': 2, **SECRET_FIELDS},
            {'id': LEADER, 'name': 'Тимлид', 'description': 'Лидер', 'status': 'idle', 'visibility': 'workspace',
             'archived_at': None, 'max_concurrent_tasks': 2, **SECRET_FIELDS},
        ]
        self.squads = [{'id': SQUAD, 'name': 'Сквад', 'leader_id': LEADER, 'archived_at': None, 'instructions': 'СКВАД-СЕКРЕТ'}]
        self.issues = {}
        self.comments = {}
        self.tasks = []
        self.rerun_calls = 0
        self.fail = {}  # (method, path) → (status, body)
        self.add_issue('TST-1', 'Свежая', status='todo', assignee=('agent', AGENT_A), minutes_ago=5)

    def add_issue(self, identifier, title, status='todo', assignee=('agent', AGENT_A), minutes_ago=0, workspace=WS):
        number = int(identifier.split('-')[1])
        iid = f'dddddddd-0000-4000-8000-{number:012d}'
        stamp = iso(self.now, minutes_ago)
        self.issues[iid] = {
            'id': iid, 'identifier': identifier, 'number': number, 'title': title, 'description': f'Описание {identifier}',
            'status': status, 'status_name': status, 'priority': 'none', 'assignee_type': assignee[0] if assignee else None,
            'assignee_id': assignee[1] if assignee else None, 'workspace_id': workspace, 'created_at': stamp,
            'updated_at': stamp, 'last_activity_at': stamp, 'attachments': [{'url': 'https://files.invalid/x'}]}
        return iid

    def add_task(self, issue_id, agent_id, status):
        tid = f'eeeeeeee-0000-4000-8000-{len(self.tasks) + 1:012d}'
        task = {'id': tid, 'issue_id': issue_id, 'agent_id': agent_id, 'status': status, 'kind': 'direct', 'attempt': 1,
                'created_at': iso(self.now), 'error': None, 'work_dir': '/srv/секрет', 'result': {'внутри': 1}}
        self.tasks.append(task)
        return tid

    def find_issue(self, ref):
        return next((i for i in self.issues.values() if ref in (i['id'], i['identifier'])), None)

    def handle(self, method, path, query, headers, body):
        with self.lock:
            self.requests.append({'method': method, 'path': path, 'query': query, 'body': body, 'headers': headers})
        if (method, path) in self.fail:
            return self.fail[(method, path)]
        ws = headers.get('X-Workspace-Id')
        if method == 'GET' and path == '/api/workspaces':
            return 200, self.workspaces
        if method == 'GET' and path == '/api/agents':
            return 200, self.agents
        if method == 'GET' and path == '/api/squads':
            return 200, self.squads
        if method == 'GET' and path == '/api/agent-task-snapshot':
            active = {'queued', 'dispatched', 'running', 'waiting_local_directory'}
            return 200, [{**t, 'issue_identifier': self.issues[t['issue_id']]['identifier']} for t in self.tasks if t['status'] in active]
        if method == 'GET' and path == '/api/issues':
            rows = [i for i in self.issues.values() if i['workspace_id'] == ws
                    and query.get('status', [i['status']])[0] == i['status']
                    and query.get('assignee_id', [i['assignee_id']])[0] == i['assignee_id']]
            limit, offset = int(query.get('limit', ['50'])[0]), int(query.get('offset', ['0'])[0])
            return 200, {'issues': rows[offset:offset + limit], 'total': len(rows), 'has_more': offset + limit < len(rows),
                         'limit': limit, 'offset': offset}
        m = re.fullmatch(r'/api/issues/([^/]+)(/[a-z-]+)?', path)
        if m:
            issue = self.find_issue(m.group(1))
            if issue is None:
                return 404, {'error': 'issue not found'}
            sub = m.group(2)
            if method == 'GET' and sub is None:
                return 200, issue
            if method == 'GET' and sub == '/comments':
                return 200, self.comments.get(issue['id'], [])
            if method == 'GET' and sub == '/task-runs':
                return 200, [t for t in self.tasks if t['issue_id'] == issue['id']]
            if method == 'PUT' and sub is None:
                body = dict(body)
                body.pop('suppress_run', None)
                issue.update(body)
                issue['last_activity_at'] = iso(self.now)
                return 200, issue
            if method == 'POST' and sub == '/comments':
                comment = {'id': f'ffffffff-0000-4000-8000-{len(self.comments.get(issue["id"], [])) + 1:012d}', 'author_type': 'member',
                           'author_id': 'svc', 'content': body['content'], 'created_at': iso(self.now), 'parent_id': None, 'attachments': []}
                self.comments.setdefault(issue['id'], []).append(comment)
                if not body['content'].lstrip().lower().startswith('/note') and issue['assignee_id']:
                    self.add_task(issue['id'], issue['assignee_id'], 'queued')
                return 201, comment
            if method == 'POST' and sub == '/rerun':
                self.rerun_calls += 1
                agent = issue['assignee_id']
                if issue['assignee_type'] == 'squad':
                    agent = next(s['leader_id'] for s in self.squads if s['id'] == agent)
                tid = self.add_task(issue['id'], agent, 'queued')
                return 202, next(t for t in self.tasks if t['id'] == tid)
        m = re.fullmatch(r'/api/tasks/([^/]+)/cancel', path)
        if method == 'POST' and m:
            task = next((t for t in self.tasks if t['id'] == m.group(1)), None)
            if task is None:
                return 404, {'error': 'task not found'}
            task['status'] = 'cancelled'
            return 200, task
        m = re.fullmatch(r'/api/agents/([^/]+)/tasks', path)
        if method == 'GET' and m:
            return 200, [t for t in self.tasks if t['agent_id'] == m.group(1)]
        return 404, {'error': f'нет маршрута {method} {path}'}


class FakeOpener:
    """Транспорт Api без сети: запрос разбирается и отдаётся FakeMultica, как это сделал бы сервер."""

    class Response:
        def __init__(self, payload):
            self.data = json.dumps(payload).encode()

        def read(self, n=-1):
            return self.data if n < 0 else self.data[:n]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def __init__(self, fake):
        self.fake = fake
        self.down = False

    def open(self, req, timeout=None):
        from urllib.parse import parse_qs, urlsplit
        if self.down:
            raise urllib.error.URLError('connection refused')
        url = urlsplit(req.full_url)
        headers = {k.title(): v for k, v in req.header_items()}
        body = json.loads(req.data) if req.data else None
        if headers.get('Authorization') != f'Bearer {PAT}':
            status, payload = 401, {'error': 'bad token'}
        else:
            status, payload = self.fake.handle(req.get_method(), url.path, parse_qs(url.query), headers, body)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, 'err', {}, io.BytesIO(json.dumps(payload).encode()))
        return self.Response(payload)


def can_listen_tcp():
    """В песочнице validate разрешён только AF_UNIX: тесты с настоящим TCP там пропускаются."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
        return True
    except OSError:
        return False


class McpCase(unittest.TestCase):
    """Фейковый API + настоящий сервис + (по требованию) настоящий HTTP-сервер MCP."""
    NOW = 1_800_000_000.0
    workspaces = ('stt', 'toons')

    def setUp(self):
        self.fake = FakeMultica(self.NOW)
        self.opener = FakeOpener(self.fake)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.config = Config(api_url='http://multica.invalid', pat=PAT, key=KEY, workspaces=self.workspaces, state_dir=self.state,
                             port=0, allowed_hosts=('127.0.0.1', 'localhost'), max_body=2048, auth_fail_limit=5)
        self.audit = AuditLog(self.state / 'audit.jsonl', self.config.secrets)
        self.api = Api(self.config.api_url, PAT, 5, self.config.secrets, opener=self.opener)
        self.service = Service(self.api, self.workspaces, self.audit, clock=lambda: self.NOW)

    def call(self, name, **args):
        is_error, payload = self.service.call_tool(name, args, '203.0.113.9')
        return is_error, payload

    def ok(self, name, **args):
        is_error, payload = self.call(name, **args)
        self.assertFalse(is_error, payload)
        return payload

    def err(self, name, **args):
        is_error, payload = self.call(name, **args)
        self.assertTrue(is_error, payload)
        return payload['error']

    def start_http(self):
        self.limiter = AuthLimiter(self.config.auth_fail_limit, self.config.auth_fail_window)
        self.handler = make_handler(self.config, self.service, self.limiter)

    def http(self, method='POST', path='/mcp', body=None, headers=None, raw=None, peer='127.0.0.1'):
        """Настоящий HTTP-обмен с настоящим обработчиком, но по socketpair (AF_UNIX): сеть в песочнице закрыта."""
        server_sock, client_sock = socket.socketpair()
        client_sock.settimeout(2)
        worker = threading.Thread(target=self.handler, args=(server_sock, (peer, 50000), object()), daemon=True)
        worker.start()
        conn = http.client.HTTPConnection('127.0.0.1', timeout=10)
        conn.sock = client_sock
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        try:
            conn.request(method, path, body=data, headers={'Host': '127.0.0.1', **(headers or {})})
            resp = conn.getresponse()
            text = resp.read()
        finally:
            conn.close()
            worker.join(5)
            server_sock.close()
        return resp.status, text, resp

    def rpc(self, method, params=None, key=KEY, headers=None, msg_id=1, peer='127.0.0.1'):
        h = {'Content-Type': 'application/json', **({'Authorization': f'Bearer {key}'} if key else {}), **(headers or {})}
        message = {'jsonrpc': '2.0', 'id': msg_id, 'method': method, **({'params': params} if params is not None else {})}
        status, text, _ = self.http(body=message, headers=h, peer=peer)
        return status, json.loads(text) if text else None

    def tool(self, name, **args):
        status, body = self.rpc('tools/call', {'name': name, 'arguments': args})
        self.assertEqual(status, 200)
        return body['result']

    def writes(self):
        return [r for r in self.fake.requests if r['method'] != 'GET']

    def audit_lines(self):
        path = self.state / 'audit.jsonl'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
