"""Таблица глаголов: единый источник для разбора аргументов (harness-priv), сборки argv (MCP) и схем инструментов.

CLI пересылает свои аргументы в harness-priv как есть, MCP собирает их из JSON по этой же таблице, поэтому
оба адаптера дают один и тот же запрос и один и тот же ответ.
"""
import re

from .errors import HarnessError

COMPONENT = {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9-]{0,39}$', 'description': 'Имя компонента из inspect'}
REASON = {'type': 'string', 'maxLength': 500, 'description': 'Зачем (до 500 символов): сохраняется в аудите, не исполняется'}
KEY = {'type': 'string', 'pattern': '^[A-Za-z0-9._:-]{1,80}$',
       'description': 'Ключ идемпотентности: повтор с тем же ключом возвращает ту же операцию'}

COMMANDS = {
    'inspect': {
        'doc': 'Состояние обвязки: версия, дрейф файлов, юниты, последняя операция, разрешённые действия, зависимости, health. Без секретов.',
        'args': [('component', COMPONENT, False)], 'options': {}},
    'validate': {
        'doc': 'Проверить коммит компонента в песочнице без сети и root. Возвращает operation_id; ход — op/log.',
        'args': [('component', COMPONENT, True), ('sha', {'type': 'string', 'pattern': '^[0-9a-f]{40}$', 'description': 'Полный sha1 коммита из монорепо'}, True)],
        'options': {'key': KEY, 'reason': REASON}},
    'deploy': {
        'doc': 'Выкатить проверенный артефакт: нужен успешный validate и его digest. Health по плановому запуску, при сбое один откат.',
        'args': [('component', COMPONENT, True)],
        'options': {'validation': {'type': 'string', 'pattern': '^[0-9]{13}-[0-9a-f]{8}$', 'description': 'operation_id успешной validate', 'required': True},
                    'digest': {'type': 'string', 'pattern': '^sha256:[0-9a-f]{64}$', 'description': 'digest из результата validate', 'required': True},
                    'key': KEY, 'reason': REASON}},
    'rollback': {
        'doc': 'Вернуть последнюю проверенную рабочую версию (или --to релиз). После неудачного отката компонент заблокирован до следующего rollback.',
        'args': [('component', COMPONENT, True)],
        'options': {'to': {'type': 'string', 'pattern': '^(baseline|[0-9a-f]{64})$', 'description': 'baseline или digest релиза'}, 'reason': REASON}},
    'op': {
        'doc': 'Состояние операции: статус, запрос, результат, причина отказа, журнал переходов.',
        'args': [('id', {'type': 'string', 'pattern': '^[0-9]{13}-[0-9a-f]{8}$'}, True)], 'options': {}},
    'log': {
        'doc': 'Полный лог операции (проверки, вывод тестов, причина отказа) без секретов.',
        'args': [('id', {'type': 'string', 'pattern': '^[0-9]{13}-[0-9a-f]{8}$'}, True)],
        'options': {'tail': {'type': 'integer', 'minimum': 1, 'maximum': 10000, 'description': 'Только последние N строк'}}},
    'ops': {
        'doc': 'Последние операции, всех компонентов или одного.',
        'args': [('component', COMPONENT, False)], 'options': {}},
}


def _check(value, schema, name):
    if schema['type'] == 'integer':
        if isinstance(value, bool) or not isinstance(value, int) or not schema.get('minimum', value) <= value <= schema.get('maximum', value):
            raise HarnessError('bad_request', f'{name}: целое от {schema.get("minimum")} до {schema.get("maximum")}')
    else:
        if not isinstance(value, str):
            raise HarnessError('bad_request', f'{name}: нужна строка')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'], value):
            raise HarnessError('bad_request', f'{name}: не соответствует {schema["pattern"]}')
        if len(value) > schema.get('maxLength', 10 ** 6):
            raise HarnessError('bad_request', f'{name}: не больше {schema["maxLength"]} символов')


def parse(verb, tokens):
    """argv после глагола → dict аргументов. Лишнее и недостающее — bad_request."""
    spec = COMMANDS[verb]
    tokens = [t for t in tokens if t != '--json']
    out, positional, i = {}, [], 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith('--'):
            name = t[2:]
            if name not in spec['options']:
                raise HarnessError('bad_request', f'{verb}: неизвестная опция {t[:40]}')
            if i + 1 >= len(tokens):
                raise HarnessError('bad_request', f'{verb}: у {t} нет значения')
            raw = tokens[i + 1]
            out[name] = int(raw) if spec['options'][name]['type'] == 'integer' and re.fullmatch(r'\d{1,6}', raw) else raw
            i += 2
        else:
            positional.append(t)
            i += 1
    if len(positional) > len(spec['args']):
        raise HarnessError('bad_request', f'{verb}: лишние аргументы')
    for (name, schema, required), value in zip(spec['args'], positional):
        out[name] = value
    return validate_args(verb, out)


def validate_args(verb, args):
    spec = COMMANDS[verb]
    allowed = {n for n, _, _ in spec['args']} | set(spec['options'])
    extra = set(args) - allowed
    if extra:
        raise HarnessError('bad_request', f'{verb}: неизвестные аргументы {sorted(extra)}')
    for name, schema, required in spec['args']:
        if name in args:
            _check(args[name], schema, name)
        elif required:
            raise HarnessError('bad_request', f'{verb}: не хватает {name}')
    for name, schema in spec['options'].items():
        if name in args:
            _check(args[name], schema, name)
        elif schema.get('required'):
            raise HarnessError('bad_request', f'{verb}: не хватает --{name}')
    return args


def tokenize(verb, args):
    """dict аргументов (из MCP) → argv для harness-priv. Тот же порядок, что принимает parse()."""
    validate_args(verb, args)
    spec = COMMANDS[verb]
    tokens = [str(args[n]) for n, _, _ in spec['args'] if n in args]
    for name in spec['options']:
        if name in args:
            tokens += [f'--{name}', str(args[name])]
    return tokens


def input_schema(verb):
    spec = COMMANDS[verb]
    props, required = {}, []
    for name, schema, req in spec['args']:
        props[name] = schema
        if req:
            required.append(name)
    for name, schema in spec['options'].items():
        props[name] = {k: v for k, v in schema.items() if k != 'required'}
        if schema.get('required'):
            required.append(name)
    return {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}
