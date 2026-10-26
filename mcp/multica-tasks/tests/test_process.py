"""Запуск настоящего процесса bin/multica-tasks-mcp: старт, health, SIGTERM, отказ при плохой конфигурации."""
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time
import unittest

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qs, urlsplit

from support import KEY, PAT, PKG, McpCase, can_listen_tcp


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class TcpFake:
    """Фейковый Multica API по TCP — только для теста настоящего процесса."""

    def __init__(self, fake):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlsplit(self.path)
                headers = {k.title(): v for k, v in self.headers.items()}
                status, payload = fake.handle('GET', url.path, parse_qs(url.query), headers, None)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@unittest.skipUnless(can_listen_tcp(), 'нет TCP (песочница validate): процесс проверяется в dev и qa')
class Process(McpCase):
    def setUp(self):
        super().setUp()
        self.tcp_fake = TcpFake(self.fake)
        self.addCleanup(self.tcp_fake.close)

    def env(self, **extra):
        return {'PATH': '/usr/bin:/bin', 'MULTICA_MCP_KEY': KEY, 'MULTICA_PAT': PAT, 'MULTICA_API_URL': self.tcp_fake.url,
                'MULTICA_MCP_WORKSPACES': 'stt', 'STATE_DIRECTORY': str(self.state), 'MULTICA_MCP_PORT': str(self.port), **extra}

    def spawn(self, **extra):
        return subprocess.Popen([sys.executable, '-I', str(PKG / 'bin' / 'multica-tasks-mcp')], env=self.env(**extra),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    @staticmethod
    def reap(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate()

    def get(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        try:
            conn.request('GET', path)
            return conn.getresponse().status
        finally:
            conn.close()

    def test_старт_health_и_корректная_остановка(self):
        self.port = free_port()
        proc = self.spawn()
        self.addCleanup(self.reap, proc)
        for _ in range(100):
            try:
                self.assertEqual(self.get('/healthz'), 200)
                break
            except OSError:
                time.sleep(0.05)
        else:
            self.fail('сервер не поднялся: ' + proc.stderr.read())
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('POST', '/mcp', json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}),
                     {'Authorization': f'Bearer {KEY}', 'Host': '127.0.0.1'})
        self.assertEqual(len(json.loads(conn.getresponse().read())['result']['tools']), 9)
        conn.close()
        probe = subprocess.run([sys.executable, '-I', str(PKG / 'deploy' / 'probe.py'), '--smoke'],
                               env=self.env(), capture_output=True, text=True, timeout=15)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertIn('healthz=200; unauthenticated=401; tools=9; bad-origin=403', probe.stdout)
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 0)
        logs = proc.stderr.read()
        self.assertNotIn(KEY, logs)
        self.assertNotIn(PAT, logs)

    def test_плохая_конфигурация_завершает_процесс_кодом_2_без_секретов(self):
        self.port = free_port()
        proc = self.spawn(MULTICA_MCP_KEY='короткий')
        _, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('MULTICA_MCP_KEY', err)
        self.assertNotIn(PAT, err)


if __name__ == '__main__':
    unittest.main()
