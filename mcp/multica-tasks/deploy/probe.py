"""Local container health; --smoke also checks MCP without calling the API."""
import http.client
import json
import os
import sys


def request(method, path, body=None, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', int(os.environ.get('MULTICA_MCP_PORT', '8101')), timeout=3)
    try:
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def main():
    status, data = request('GET', '/healthz')
    if status != 200 or json.loads(data).get('status') != 'ok':
        raise RuntimeError('healthz failed')
    if '--smoke' in sys.argv:
        if request('POST', '/mcp', '{}')[0] != 401:
            raise RuntimeError('unauthenticated MCP request must fail')
        headers = {'Authorization': 'Bearer ' + os.environ['MULTICA_MCP_KEY'], 'Content-Type': 'application/json'}
        status, data = request('POST', '/mcp', json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}), headers)
        if status != 200 or len(json.loads(data)['result']['tools']) != 9:
            raise RuntimeError('MCP tool list failed')
        status, _ = request('POST', '/mcp', '{}', dict(headers, Origin='https://evil.example'))
        if status != 403:
            raise RuntimeError('untrusted Origin must fail')
        print('healthz=200; unauthenticated=401; tools=9; bad-origin=403')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        # Health output must never contain tokens or request headers.
        print('MCP probe failed', file=sys.stderr)
        sys.exit(1)
