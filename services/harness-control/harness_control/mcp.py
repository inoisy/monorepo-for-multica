"""MCP-сервер harness-control (stdio, построчный JSON-RPC). Тонкий адаптер над client.call, как stand-mcp над stand."""
import json
import sys

from . import client
from .commands import COMMANDS, input_schema, tokenize
from .errors import HarnessError

PROTOCOL = '2025-06-18'
TOOLS = [{'name': f'harness_{verb}', 'description': spec['doc'], 'inputSchema': input_schema(verb)} for verb, spec in COMMANDS.items()]
BY_NAME = {t['name']: verb for t, verb in zip(TOOLS, COMMANDS)}


def call_tool(name, arguments, call=client.call):
    """(isError, text): text — тот же JSON, что печатает CLI."""
    verb = BY_NAME.get(name)
    if verb is None:
        return True, client.dumps(client.unknown_verb(str(name or '').removeprefix('harness_')))
    try:
        tokens = tokenize(verb, arguments or {})
    except HarnessError as e:
        return True, client.dumps(e.to_dict())
    result = call(verb, tokens)
    return client.is_error(result), client.dumps(result)


def reply(out, msg_id, result=None, error=None):
    msg = {'jsonrpc': '2.0', 'id': msg_id}
    msg['error' if error else 'result'] = error or result
    out.write(json.dumps(msg, ensure_ascii=False) + '\n')
    out.flush()


def handle(msg, out, call=client.call):
    method, msg_id = msg.get('method'), msg.get('id')
    if msg_id is None:
        return
    if method == 'initialize':
        version = (msg.get('params') or {}).get('protocolVersion') or PROTOCOL
        reply(out, msg_id, {'protocolVersion': version, 'capabilities': {'tools': {}},
                            'serverInfo': {'name': 'harness-control', 'version': '1.0.0'}})
    elif method == 'ping':
        reply(out, msg_id, {})
    elif method == 'tools/list':
        reply(out, msg_id, {'tools': TOOLS})
    elif method == 'tools/call':
        params = msg.get('params') or {}
        is_error, text = call_tool(params.get('name'), params.get('arguments'), call)
        reply(out, msg_id, {'content': [{'type': 'text', 'text': text}], 'isError': is_error})
    else:
        reply(out, msg_id, error={'code': -32601, 'message': f'method not found: {method}'})


def main(stdin=sys.stdin, out=sys.stdout, call=client.call):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply(out, None, error={'code': -32700, 'message': 'parse error'})
            continue
        try:
            handle(msg, out, call)
        except Exception as e:  # один плохой вызов не должен ронять сервер
            if isinstance(msg, dict) and msg.get('id') is not None:
                reply(out, msg['id'], error={'code': -32603, 'message': str(e)})
    return 0
