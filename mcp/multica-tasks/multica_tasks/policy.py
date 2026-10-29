"""Что можно запустить: allowlist по префиксу argv и запрещённые флаги. Единственная таблица — ALLOW."""
from .errors import InvalidParams

# Префикс из слов команды → слова, которые дальше в argv запрещены (подкоманды записи, раскрывающие лишнее).
ALLOW = {
    ('issue',): frozenset(),
    ('project', 'list'): frozenset(),
    ('project', 'get'): frozenset(),
    ('agent', 'list'): frozenset(),
    ('agent', 'get'): frozenset(),
    ('agent', 'models'): frozenset({'personal', 'profile', 'reset', 'set', 'single', 'tools'}),
    ('agent', 'tasks'): frozenset(),
    ('squad', 'list'): frozenset(),
    ('squad', 'member', 'list'): frozenset(),
    ('profile', 'list'): frozenset(),
    ('workflow', 'list'): frozenset(),
    ('label', 'list'): frozenset(),
    ('property', 'list'): frozenset(),
    ('skill', 'list'): frozenset(),
    ('skill', 'get'): frozenset(),
    ('runtime', 'unavailable'): frozenset({'recheck'}),
    ('subscription', 'list'): frozenset(),
    ('workspace', 'list'): frozenset(),
    ('version',): frozenset(),
}

# Команды, которым воркспейс не нужен: справка, версия, список воркспейсов самого человека.
NO_WORKSPACE_PREFIXES = frozenset({(), ('version',), ('workspace', 'list')})

# Флаги, которые читают файлы сервера или уводят токен на чужой адрес и в чужой профиль.
GLOBAL_FLAGS = frozenset({'--server-url', '--profile', '--workspace-id', '--debug'})
FLAGS_BY_PREFIX = {('skill', 'get'): frozenset({'--with-content'})}
HELP_FLAGS = frozenset({'--help', '-h'})
ONLY_SSH = 'только по ssh'


def _deny(reason):
    raise InvalidParams(f'{ONLY_SSH}: {reason}', denied=reason)


def _flag_name(token):
    return token.split('=', 1)[0] if token.startswith('--') else token


def _forbidden_flag(name, prefix):
    return (name.endswith('-file') or name.startswith('--attach') or name in GLOBAL_FLAGS
            or name in FLAGS_BY_PREFIX.get(prefix, ()))


def _match(argv):
    """Самый длинный префикс ALLOW: слова команды стоят первыми, флагов между ними нет."""
    for prefix in sorted(ALLOW, key=len, reverse=True):
        if tuple(argv[:len(prefix)]) == prefix:
            return prefix
    return None


def _is_group_help(argv):
    """`--help`, `agent --help`, `squad member --help`: справка по группе с разрешёнными подкомандами."""
    if argv == ['--help'] or argv == ['-h']:
        return True
    words = argv[:-1]
    return (argv[-1] in HELP_FLAGS and bool(words) and not any(w.startswith('-') for w in words)
            and any(prefix[:len(words)] == tuple(words) for prefix in ALLOW))


def check(argv):
    """Бросает InvalidParams (-32602), если команду нельзя запускать; иначе возвращает совпавший префикс."""
    if not argv:
        _deny('пустая команда')
    prefix = _match(argv)
    if prefix is None:
        if _is_group_help(argv):
            return ()
        _deny(f'команда {" ".join(argv[:3])!r} вне allowlist')
    for token in argv:
        if token.startswith('-') and _forbidden_flag(_flag_name(token), prefix):
            _deny(f'флаг {_flag_name(token)} запрещён')
    banned = ALLOW[prefix]
    for token in argv[len(prefix):]:
        if token in banned:
            _deny(f'подкоманда {token} запрещена')
    return prefix


def wants_output_flag(argv):
    """Добавлять ли `--output json`: справке и version он не нужен, явный --output не трогаем."""
    if any(t in HELP_FLAGS for t in argv) or argv[0] == 'version':
        return False
    return not any(t == '--output' or t.startswith('--output=') for t in argv)


def needs_workspace(prefix, argv):
    return prefix not in NO_WORKSPACE_PREFIXES and not any(t in HELP_FLAGS for t in argv)
