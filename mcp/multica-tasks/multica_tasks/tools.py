"""Схемы инструментов и проверка аргументов. Поведение — в service.py; здесь только контракт для клиента."""
from .errors import ToolError

WORKSPACE = {'type': 'string', 'description': 'Воркспейс: slug, имя или id. Можно не указывать, если разрешён один.'}
ISSUE = {'type': 'string', 'description': 'Задача: ключ (TST-272) или UUID.'}
AGENT = {'type': 'string', 'description': 'Агент: имя или UUID.'}


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


TOOLS = {
    'list_workspaces': {
        'description': 'Воркспейсы Multica, доступные этому коннектору.',
        'write': False,
        'inputSchema': _schema({}),
    },
    'list_agents': {
        'description': 'Агенты воркспейса: статус и текущие раны (task_id, задача, статус рана). Инструкции и настройки агентов не отдаются.',
        'write': False,
        'inputSchema': _schema({'workspace': WORKSPACE}),
    },
    'list_issues': {
        'description': 'Задачи воркспейса с фильтрами. stale_minutes=N возвращает «зависшие»: статус todo или in_progress, '
                       'исполнитель — агент или сквад, активного рана нет, последняя активность старше N минут.',
        'write': False,
        'inputSchema': _schema({
            'workspace': WORKSPACE,
            'status': {'type': 'string', 'description': 'Ключ статуса: todo, in_progress, dev, qa, review…'},
            'assignee': {'type': 'string', 'description': 'Исполнитель-агент: имя или UUID.'},
            'stale_minutes': {'type': 'integer', 'minimum': 1, 'maximum': 525600},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 50},
            'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
        }),
    },
    'get_issue': {
        'description': 'Задача: описание, последние комментарии (по умолчанию 10) и раны со статусами.',
        'write': False,
        'inputSchema': _schema({
            'workspace': WORKSPACE, 'issue': ISSUE,
            'comments': {'type': 'integer', 'minimum': 0, 'maximum': 50, 'default': 10},
        }, ['issue']),
    },
    'list_agent_tasks': {
        'description': 'Последние раны агента.',
        'write': False,
        'inputSchema': _schema({
            'workspace': WORKSPACE, 'agent': AGENT,
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 20},
        }, ['agent']),
    },
    'comment_issue': {
        'description': 'Комментарий к задаче от имени сервисного пользователя «Claude (MCP)». По умолчанию без рана '
                       '(текст получает префикс /note). wake=true публикует обычный комментарий, который будит исполнителя.',
        'write': True,
        'inputSchema': _schema({
            'workspace': WORKSPACE, 'issue': ISSUE,
            'text': {'type': 'string', 'minLength': 1, 'maxLength': 20000},
            'wake': {'type': 'boolean', 'default': False},
        }, ['issue', 'text']),
    },
    'update_issue': {
        'description': 'Сменить статус и/или исполнителя (агент или сквад; «none» снимает). Сама смена рана не создаёт; '
                       'при смене исполнителя ран ставится ровно один (wake по умолчанию true). Статус → todo агента не будит: нужен wake=true.',
        'write': True,
        'inputSchema': _schema({
            'workspace': WORKSPACE, 'issue': ISSUE,
            'status': {'type': 'string', 'description': 'Ключ статуса.'},
            'assignee': {'type': 'string', 'description': 'Агент или сквад: имя или UUID; «none» — снять исполнителя.'},
            'wake': {'type': 'boolean', 'description': 'Поставить ран исполнителю после изменения (дедуп как у wake_issue).'},
        }, ['issue']),
    },
    'wake_issue': {
        'description': 'Поставить исполнителю ровно один ран. Если у исполнителя уже есть активный ран по задаче — вернёт '
                       'already_active и ничего не создаст.',
        'write': True,
        'inputSchema': _schema({'workspace': WORKSPACE, 'issue': ISSUE}, ['issue']),
    },
    'cancel_task': {
        'description': 'Отменить ран по task_id (id из get_issue, list_agent_tasks, list_agents).',
        'write': True,
        'inputSchema': _schema({
            'workspace': WORKSPACE,
            'task_id': {'type': 'string', 'description': 'UUID рана.'},
        }, ['task_id']),
    },
}

TYPES = {'string': str, 'integer': int, 'boolean': bool}


def public_list():
    return [{'name': name, 'description': spec['description'], 'inputSchema': spec['inputSchema']}
            for name, spec in TOOLS.items()]


def validate(name, arguments):
    """Возвращает аргументы с подставленными умолчаниями или бросает ToolError(invalid_argument)."""
    schema = TOOLS[name]['inputSchema']
    props = schema['properties']
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolError('invalid_argument', 'arguments: нужен объект')
    extra = sorted(set(arguments) - set(props))
    if extra:
        raise ToolError('invalid_argument', f'неизвестные аргументы: {", ".join(extra)}')
    missing = [k for k in schema['required'] if k not in arguments]
    if missing:
        raise ToolError('invalid_argument', f'не хватает аргументов: {", ".join(missing)}')
    out = {}
    for key, value in arguments.items():
        spec = props[key]
        expected = TYPES[spec['type']]
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise ToolError('invalid_argument', f'{key}: ожидается {spec["type"]}')
        if isinstance(value, str):
            if len(value) < spec.get('minLength', 0) or len(value) > spec.get('maxLength', 1000):
                raise ToolError('invalid_argument', f'{key}: длина вне допустимого')
        if isinstance(value, int) and not isinstance(value, bool):
            if value < spec.get('minimum', value) or value > spec.get('maximum', value):
                raise ToolError('invalid_argument', f'{key}: вне диапазона {spec.get("minimum")}…{spec.get("maximum")}')
        out[key] = value
    for key, spec in props.items():
        if key not in out and 'default' in spec:
            out[key] = spec['default']
    return out
