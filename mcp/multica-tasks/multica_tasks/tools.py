"""Схема единственного инструмента `multica` и проверка аргументов. Поведение — в service.py."""
from .errors import InvalidParams

MAX_ARGS = 200
MAX_ARG_LENGTH = 16000
MAX_STDIN_BYTES = 256 * 1024

TOOLS = {
    'multica': {
        'description': (
            'Командная строка Multica (тот же `multica` CLI, что у агентов), от имени владельца ключа. '
            'args — argv без имени бинаря: ["issue","get","TST-123"]. Длинный текст — через stdin и флаги '
            '--content-stdin / --description-stdin; флаги *-file и --attach* запрещены. По умолчанию ответ в JSON '
            '(--output json добавляется сам). Справка: ["issue","create","--help"]. Доступны issue *, чтение '
            'project/agent/squad/profile/workflow/label/property/skill/runtime unavailable/subscription/workspace; '
            'остальное — только по ssh. Ловушки: issue create/update --assignee и issue assign --to сразу '
            'стартуют ран; issue comment add будит исполнителя; снять исполнителя — issue assign <KEY> --unassign.'),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'args': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': MAX_ARGS,
                         'description': 'argv после имени бинаря, строки как есть, без shell.'},
                'stdin': {'type': 'string', 'description': 'Текст для --content-stdin / --description-stdin, до 256 КБ.'},
                'workspace': {'type': 'string', 'description': 'Воркспейс: slug, имя или id. Обязателен, если ключу разрешено больше одного.'},
            },
            'required': ['args'],
            'additionalProperties': False,
        },
    },
}


def public_list():
    return [{'name': name, 'description': spec['description'], 'inputSchema': spec['inputSchema']}
            for name, spec in TOOLS.items()]


def validate(arguments):
    """Возвращает (args, stdin, workspace) или бросает InvalidParams."""
    if not isinstance(arguments, dict):
        raise InvalidParams('arguments: нужен объект')
    extra = sorted(set(arguments) - {'args', 'stdin', 'workspace'})
    if extra:
        raise InvalidParams(f'неизвестные аргументы: {", ".join(extra)}')
    args = arguments.get('args')
    if not isinstance(args, list) or not args or len(args) > MAX_ARGS or not all(isinstance(a, str) for a in args):
        raise InvalidParams(f'args: нужен непустой массив строк (до {MAX_ARGS})')
    if any(len(a) > MAX_ARG_LENGTH or '\x00' in a for a in args):
        raise InvalidParams(f'args: элемент длиннее {MAX_ARG_LENGTH} символов или с нулевым байтом')
    stdin = arguments.get('stdin', '')
    if not isinstance(stdin, str) or len(stdin.encode()) > MAX_STDIN_BYTES:
        raise InvalidParams('stdin: нужна строка до 256 КБ')
    workspace = arguments.get('workspace')
    if workspace is not None and (not isinstance(workspace, str) or not workspace.strip() or len(workspace) > 200):
        raise InvalidParams('workspace: нужна непустая строка')
    return args, stdin, workspace.strip() if workspace else None
