"""Что можно запустить: явный перечень команд COMMANDS, всё остальное запрещено.

Новая подкоманда CLI через MCP недоступна, пока её не внесут в таблицу.
"""
from .errors import InvalidParams

READ, WRITE = 'read', 'write'

# Путь команды (слова до первого флага) → (доступ, слова, которые дальше в argv запрещены).
COMMANDS = {
    ('issue', 'list'): (READ, ()),
    ('issue', 'get'): (READ, ()),
    ('issue', 'search'): (READ, ()),
    ('issue', 'children'): (READ, ()),
    ('issue', 'pull-requests'): (READ, ()),
    ('issue', 'timeline'): (READ, ()),
    ('issue', 'runs'): (READ, ()),
    ('issue', 'run-messages'): (READ, ()),
    ('issue', 'usage'): (READ, ()),
    ('issue', 'comment', 'list'): (READ, ()),
    ('issue', 'subscriber', 'list'): (READ, ()),
    ('issue', 'label', 'list'): (READ, ()),
    ('issue', 'metadata', 'list'): (READ, ()),
    ('issue', 'metadata', 'get'): (READ, ()),
    ('issue', 'property', 'list'): (READ, ()),
    ('issue', 'wakeup', 'list'): (READ, ()),
    ('issue', 'wakeup', 'get'): (READ, ()),
    ('issue', 'wakeup', 'runs'): (READ, ()),
    ('issue', 'wakeup', 'events'): (READ, ()),
    ('issue', 'create'): (WRITE, ()),
    ('issue', 'update'): (WRITE, ()),
    ('issue', 'assign'): (WRITE, ()),
    ('issue', 'status'): (WRITE, ()),
    ('issue', 'reorder'): (WRITE, ()),
    ('issue', 'rerun-task'): (WRITE, ()),
    ('issue', 'cancel-task'): (WRITE, ()),
    ('issue', 'steer'): (WRITE, ()),  # и `steer retry`
    ('issue', 'model-profile'): (WRITE, ()),  # показ и смена одной командой
    ('issue', 'stages'): (WRITE, ()),  # показ и смена одной командой
    ('issue', 'comment', 'add'): (WRITE, ()),
    ('issue', 'comment', 'update'): (WRITE, ()),
    ('issue', 'comment', 'resolve'): (WRITE, ()),
    ('issue', 'comment', 'unresolve'): (WRITE, ()),
    ('issue', 'subscriber', 'add'): (WRITE, ()),
    ('issue', 'subscriber', 'remove'): (WRITE, ()),
    ('issue', 'label', 'add'): (WRITE, ()),
    ('issue', 'label', 'remove'): (WRITE, ()),
    ('issue', 'metadata', 'set'): (WRITE, ()),
    ('issue', 'property', 'set'): (WRITE, ()),
    ('issue', 'property', 'unset'): (WRITE, ()),
    ('issue', 'wakeup', 'create'): (WRITE, ()),
    ('issue', 'wakeup', 'update'): (WRITE, ()),
    ('issue', 'wakeup', 'disable'): (WRITE, ()),
    ('issue', 'wakeup', 'trigger'): (WRITE, ()),
    ('issue', 'wakeup', 'checkin'): (WRITE, ()),
    ('project', 'list'): (READ, ()),
    ('project', 'get'): (READ, ()),
    ('agent', 'list'): (READ, ()),
    ('agent', 'get'): (READ, ()),
    ('agent', 'tasks'): (READ, ()),
    ('agent', 'models'): (READ, ('personal', 'profile', 'reset', 'set', 'single', 'tools')),
    ('squad', 'list'): (READ, ()),
    ('squad', 'get'): (READ, ()),
    ('squad', 'member', 'list'): (READ, ()),
    ('profile', 'list'): (READ, ()),
    ('workflow', 'list'): (READ, ()),
    ('label', 'list'): (READ, ()),
    ('property', 'list'): (READ, ()),
    ('skill', 'list'): (READ, ()),
    ('skill', 'get'): (READ, ()),
    ('runtime', 'unavailable'): (READ, ('recheck',)),
    ('subscription', 'list'): (READ, ()),
    ('workspace', 'list'): (READ, ()),
    ('version',): (READ, ()),
}

# Команды, которым воркспейс не нужен: справка, версия, список воркспейсов самого человека.
NO_WORKSPACE = frozenset({(), ('version',), ('workspace', 'list')})

# Флаги, которые читают файлы сервера или уводят токен на чужой адрес и в чужой профиль.
GLOBAL_FLAGS = frozenset({'--server-url', '--profile', '--workspace-id', '--debug'})
FLAGS_BY_PATH = {('skill', 'get'): frozenset({'--with-content'})}
HELP_FLAGS = frozenset({'--help', '-h'})
ONLY_SSH = 'только по ssh'


def _deny(reason):
    raise InvalidParams(f'{ONLY_SSH}: {reason}', denied=reason)


def _flag_name(token):
    return token.split('=', 1)[0] if token.startswith('--') else token


def _forbidden_flag(name, path):
    return (name.endswith('-file') or name.startswith('--attach') or name in GLOBAL_FLAGS
            or name in FLAGS_BY_PATH.get(path, ()))


def _command_path(argv):
    """Слова до первого флага: флаг между словами (`issue --output json comment delete`) обрывает путь."""
    words = []
    for token in argv:
        if token.startswith('-'):
            break
        words.append(token)
    return tuple(words)


def _match(argv):
    """Самый длинный путь из COMMANDS, с которого начинаются слова argv."""
    words = _command_path(argv)
    for path in sorted(COMMANDS, key=len, reverse=True):
        if words[:len(path)] == path:
            return path
    return None


def is_help(argv):
    """Справка, только если перед --help нет флагов: в `--title --help` флаг съедает его как значение и команда выполняется."""
    return argv[-1] in HELP_FLAGS and not any(t.startswith('-') for t in argv[:-1])


def _is_group_help(argv):
    """`--help`, `agent --help`, `issue comment --help`: справка по группе с разрешёнными командами."""
    if not is_help(argv):
        return False
    words = tuple(argv[:-1])
    return any(path[:len(words)] == words for path in COMMANDS)


def check(argv, read_only=False):
    """Бросает InvalidParams (-32602), если команду нельзя запускать; иначе возвращает совпавший путь."""
    if not argv:
        _deny('пустая команда')
    path = _match(argv)
    if path is None:
        if _is_group_help(argv):
            return ()
        _deny(f'команда {" ".join(_command_path(argv)[:3])!r} вне allowlist')
    for token in argv:
        if token.startswith('-') and _forbidden_flag(_flag_name(token), path):
            _deny(f'флаг {_flag_name(token)} запрещён')
    access, banned = COMMANDS[path]
    for token in argv[len(path):]:
        if token in banned:
            _deny(f'подкоманда {token} запрещена')
    if read_only and access == WRITE and not is_help(argv):
        _deny(f'команда {" ".join(path)!r} меняет данные, а ключ только для чтения')
    return path


def wants_output_flag(argv):
    """Добавлять ли `--output json`: справке и version он не нужен, явный --output не трогаем."""
    if is_help(argv) or argv[0] == 'version':
        return False
    return not any(t == '--output' or t.startswith('--output=') for t in argv)


def needs_workspace(path, argv):
    return path not in NO_WORKSPACE and not is_help(argv)
