"""JSON-RPC 2.0 поверх MCP (stateless streamable HTTP): без сессий, на POST один JSON-ответ."""
import json

from . import tools
from .errors import InvalidParams

PROTOCOLS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
SERVER_INFO = {'name': 'multica-tasks', 'version': '2.0.0'}


def _error(msg_id, code, message):
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}}


def _result(msg_id, result):
    return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}


def handle(message, service, client_ip='', client=None):
    """Ответ-словарь или None для уведомлений."""
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
        return _error(message.get('id') if isinstance(message, dict) else None, -32600, 'invalid request')
    method, msg_id = message['method'], message.get('id')
    if msg_id is None:
        return None
    params = message.get('params') or {}
    if not isinstance(params, dict):
        return _error(msg_id, -32602, 'params: нужен объект')
    if method == 'initialize':
        asked = params.get('protocolVersion')
        return _result(msg_id, {'protocolVersion': asked if asked in PROTOCOLS else PROTOCOLS[0],
                                'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': SERVER_INFO})
    if method == 'ping':
        return _result(msg_id, {})
    if method == 'tools/list':
        return _result(msg_id, {'tools': tools.public_list()})
    if method == 'tools/call':
        name = params.get('name')
        if not isinstance(name, str) or not name:
            return _error(msg_id, -32602, 'name: нужна непустая строка')
        try:
            is_error, payload = service.call_tool(name, params.get('arguments') or {}, client_ip, client)
        except InvalidParams as e:
            # сообщение повторяет ввод клиента: маскируем секреты и здесь
            return _error(msg_id, -32602, service.redact(e.message))
        # isError — по признаку ошибки из сервиса, а не по наличию ключа в теле
        return _result(msg_id, {'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}],
                                'isError': bool(is_error)})
    return _error(msg_id, -32601, f'method not found: {method}')
