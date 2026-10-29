"""Общие подставки тестов: фейковый бинарь `multica` (пишет argv, окружение и stdin вызова) и сервер MCP.

Реальной сети, Multica и LLM нет: бинарь — скрипт рядом с behavior.json, ответы задаёт тест.
"""
import http.client
import json
import socket
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))

from multica_tasks.audit import AuditLog  # noqa: E402
from multica_tasks.config import Client, Config  # noqa: E402
from multica_tasks.http import AuthLimiter, make_handler  # noqa: E402
from multica_tasks.runner import Runner  # noqa: E402
from multica_tasks.service import Service  # noqa: E402

KEY = 'k' * 40
PAT = 'mul_secret_pat_' + 'p' * 24
ILYA_KEY = 'i' * 40
ILYA_PAT = 'mul_ilya_pat_' + 'q' * 24
WS = 'aaaaaaaa-0000-4000-8000-000000000001'
OTHER_WS = 'aaaaaaaa-0000-4000-8000-000000000002'
HIDDEN_WS = 'aaaaaaaa-0000-4000-8000-000000000003'
WORKSPACES = [{'id': WS, 'name': 'stt', 'slug': 'stt'}, {'id': OTHER_WS, 'name': 'Мульты', 'slug': 'toons'},
              {'id': HIDDEN_WS, 'name': 'Скрытый', 'slug': 'hidden'}]

FAKE_SCRIPT = '''#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
behavior = json.load(open(os.path.join(here, 'behavior.json')))
argv = sys.argv[1:]
stdin = sys.stdin.read()
env = {{k: v for k, v in os.environ.items()}}
with open(os.path.join(here, 'calls.jsonl'), 'a') as f:
    f.write(json.dumps({{'argv': argv, 'stdin': stdin, 'env': env, 'cwd': os.getcwd(), 'listing': os.listdir('.')}}) + '\\n')
if argv[0:2] == ['workspace', 'list']:
    print(json.dumps(behavior['workspaces']))
    sys.exit(0)
for rule in behavior.get('rules', []):
    if argv[:len(rule['argv'])] == rule['argv']:
        if rule.get('sleep'):
            time.sleep(rule['sleep'])
        if rule.get('reject_output') and '--output' in argv:
            sys.stderr.write('Error: unknown flag: --output\\n')
            sys.exit(1)
        sys.stdout.write(rule.get('stdout', '').replace('{{TOKEN}}', env.get('MULTICA_TOKEN', '')))
        sys.stderr.write(rule.get('stderr', '').replace('{{TOKEN}}', env.get('MULTICA_TOKEN', '')))
        sys.stdout.flush()
        sys.exit(rule.get('exit', 0))
print(json.dumps({{'argv': argv, 'token': env.get('MULTICA_TOKEN'), 'workspace': env.get('MULTICA_WORKSPACE_ID')}}))
'''


class FakeCli:
    """Каталог с фейковым `multica`: behavior.json задаёт ответы, calls.jsonl хранит вызовы."""

    def __init__(self, root):
        self.dir = Path(root)
        self.bin = self.dir / 'multica'
        self.bin.write_text(FAKE_SCRIPT.format(python=sys.executable))
        self.bin.chmod(self.bin.stat().st_mode | stat.S_IXUSR)
        self.behavior = {'workspaces': WORKSPACES, 'rules': []}
        self.save()

    def save(self):
        (self.dir / 'behavior.json').write_text(json.dumps(self.behavior))

    def rule(self, argv, **kw):
        self.behavior['rules'].append({'argv': argv, **kw})
        self.save()

    @property
    def calls(self):
        path = self.dir / 'calls.jsonl'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def can_listen_tcp():
    """В песочнице validate разрешён только AF_UNIX: тесты с настоящим TCP там пропускаются."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
        return True
    except OSError:
        return False


class McpCase(unittest.TestCase):
    """Фейковый бинарь + настоящий сервис + (по требованию) настоящий HTTP-обработчик MCP."""
    clients = (Client('Claude (MCP)', KEY, PAT, ('stt',)), Client('Илья', ILYA_KEY, ILYA_PAT, ('stt', 'toons')))
    run_overrides = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'cli').mkdir()
        (root / 'state').mkdir()
        self.cli = FakeCli(root / 'cli')
        self.state = root / 'state'
        self.config = Config(api_url='http://127.0.0.1:8080', clients=self.clients, multica_bin=str(self.cli.bin),
                             state_dir=self.state, port=0, allowed_hosts=('127.0.0.1', 'localhost'), max_body=2048 * 200,
                             auth_fail_limit=5, **self.run_overrides)
        self.audit = AuditLog(self.state / 'audit.jsonl', self.config.secrets)
        self.service = Service(Runner(self.config), self.audit)

    def client(self, name='Claude (MCP)'):
        return next(c for c in self.clients if c.name == name)

    def call(self, args, stdin=None, workspace=None, client='Claude (MCP)'):
        arguments = {'args': args, **({'stdin': stdin} if stdin is not None else {}), **({'workspace': workspace} if workspace else {})}
        return self.service.call_tool('multica', arguments, '203.0.113.9', self.client(client))

    def ok(self, args, **kw):
        is_error, payload = self.call(args, **kw)
        self.assertFalse(is_error, payload)
        return payload

    def start_http(self):
        self.limiter = AuthLimiter(self.config.auth_fail_limit, self.config.auth_fail_window)
        self.handler = make_handler(self.config, self.service, self.limiter)

    def http(self, method='POST', path='/mcp', body=None, headers=None, raw=None, peer='127.0.0.1'):
        """Настоящий HTTP-обмен с настоящим обработчиком, но по socketpair (AF_UNIX): сеть в песочнице закрыта."""
        server_sock, client_sock = socket.socketpair()
        client_sock.settimeout(5)
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
            worker.join(10)
            server_sock.close()
        return resp.status, text, resp

    def rpc(self, method, params=None, key=KEY, headers=None, msg_id=1, peer='127.0.0.1'):
        h = {'Content-Type': 'application/json', **({'Authorization': f'Bearer {key}'} if key else {}), **(headers or {})}
        message = {'jsonrpc': '2.0', 'id': msg_id, 'method': method, **({'params': params} if params is not None else {})}
        status, text, _ = self.http(body=message, headers=h, peer=peer)
        return status, json.loads(text) if text else None

    def tool(self, args, key=KEY, **extra):
        status, body = self.rpc('tools/call', {'name': 'multica', 'arguments': {'args': args, **extra}}, key=key)
        self.assertEqual(status, 200)
        return body

    def audit_lines(self):
        path = self.state / 'audit.jsonl'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
