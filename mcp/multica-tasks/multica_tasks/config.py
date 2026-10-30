"""Конфигурация из окружения и файла клиентов (права 0600). Неверная настройка — отказ на старте."""
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path

MIN_KEY_LENGTH = 32
DEFAULT_ORIGINS = ('https://claude.ai', 'https://claude.com')
DEFAULT_HOSTS = ('multica.yakutov.com', '127.0.0.1', 'localhost')
DEFAULT_CLIENT = 'Claude (MCP)'
DEFAULT_PUBLIC_URL = 'https://multica.yakutov.com'
ALL_WORKSPACES = '*'  # все воркспейсы, где состоит владелец PAT, включая появившиеся позже
TRUE = ('1', 'true', 'yes')


class ConfigError(ValueError):
    pass


def _list(value):
    return tuple(x.strip() for x in (value or '').split(',') if x.strip())


@dataclass(frozen=True)
class Client:
    """Кто ходит в MCP: ключ входа и его собственный PAT Multica — действия в задачах идут от этого человека."""
    name: str
    key: str
    token: str
    workspaces: tuple
    read_only: bool = False  # только команды чтения
    ident: str = ''  # ключ кэша и аудита: у OAuth — пользователь Multica, одинаковые отображаемые имена не смешиваются
    source: str = 'key'  # key — Bearer-ключ из конфигурации, oauth — вход через Multica

    @property
    def cache_key(self):
        return self.ident or self.name

    @property
    def any_workspace(self):
        return ALL_WORKSPACES in self.workspaces


def load_clients(path, default_workspaces):
    path = Path(path)
    try:
        mode = path.stat().st_mode
    except OSError as e:
        raise ConfigError(f'MULTICA_MCP_CLIENTS: файл недоступен ({e.strerror})') from None
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError('MULTICA_MCP_CLIENTS: файл должен быть доступен только владельцу (0600)')
    try:
        rows = json.loads(path.read_text())
    except ValueError:
        raise ConfigError('MULTICA_MCP_CLIENTS: невалидный JSON') from None
    if not isinstance(rows, list):
        raise ConfigError('MULTICA_MCP_CLIENTS: нужен массив клиентов')
    clients = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ConfigError(f'MULTICA_MCP_CLIENTS[{i}]: нужен объект')
        name, key, token = (row.get(f) for f in ('name', 'key', 'token'))
        if not all(isinstance(v, str) and v.strip() for v in (name, key, token)):
            raise ConfigError(f'MULTICA_MCP_CLIENTS[{i}]: нужны строки name, key, token')
        if len(key) < MIN_KEY_LENGTH:
            raise ConfigError(f'MULTICA_MCP_CLIENTS[{i}]: key короче {MIN_KEY_LENGTH} символов')
        workspaces = row.get('workspaces', list(default_workspaces))
        if not isinstance(workspaces, list) or not workspaces or not all(isinstance(w, str) and w.strip() for w in workspaces):
            raise ConfigError(f'MULTICA_MCP_CLIENTS[{i}]: workspaces — непустой массив строк '
                              '(или задайте MULTICA_MCP_WORKSPACES по умолчанию)')
        if ALL_WORKSPACES in workspaces and len(workspaces) > 1:
            raise ConfigError(f'MULTICA_MCP_CLIENTS[{i}]: "*" нельзя смешивать с перечнем воркспейсов')
        read_only = row.get('read_only', False)
        if not isinstance(read_only, bool):
            raise ConfigError(f'MULTICA_MCP_CLIENTS[{i}]: read_only — true или false')
        clients.append(Client(name.strip(), key.strip(), token.strip(), tuple(w.strip() for w in workspaces), read_only))
    return clients


@dataclass(frozen=True)
class Config:
    api_url: str
    clients: tuple
    oauth_key_file: Path | None = None  # ключ шифрования PAT; задан — включён вход через Multica
    public_url: str = DEFAULT_PUBLIC_URL  # issuer и база адресов OAuth; resource = public_url + /mcp
    multica_bin: str = '/usr/local/bin/multica'
    run_dir: str | None = None  # где создаются пустые cwd запусков; None — системный TMPDIR
    state_dir: Path = Path('.')
    host: str = '127.0.0.1'
    port: int = 8101
    allowed_origins: tuple = DEFAULT_ORIGINS
    allowed_hosts: tuple = DEFAULT_HOSTS
    max_body: int = 1024 * 1024
    run_timeout: float = 30.0
    max_stdin: int = 256 * 1024
    max_output: int = 64 * 1024
    max_parallel: int = 4
    auth_fail_limit: int = 10
    auth_fail_window: float = 60.0

    @property
    def secrets(self):
        return tuple(s for c in self.clients for s in (c.key, c.token))

    @classmethod
    def from_env(cls, env):
        def need(name):
            value = env.get(name, '').strip()
            if not value:
                raise ConfigError(f'{name} не задан')
            return value

        api_url = need('MULTICA_API_URL').rstrip('/')
        if not re.fullmatch(r'https?://[A-Za-z0-9.-]+(:\d+)?', api_url):
            raise ConfigError('MULTICA_API_URL: нужен http(s)://хост[:порт] без пути')
        default_workspaces = _list(env.get('MULTICA_MCP_WORKSPACES'))
        clients = []
        key = env.get('MULTICA_MCP_KEY', '').strip()
        if key:
            if len(key) < MIN_KEY_LENGTH:
                raise ConfigError(f'MULTICA_MCP_KEY короче {MIN_KEY_LENGTH} символов')
            if not default_workspaces:
                raise ConfigError('MULTICA_MCP_WORKSPACES: пустой список')
            read_only = env.get('MULTICA_MCP_READ_ONLY', '').strip().lower() in TRUE
            clients.append(Client(DEFAULT_CLIENT, key, need('MULTICA_PAT'), default_workspaces, read_only))
        if env.get('MULTICA_MCP_CLIENTS', '').strip():
            clients += load_clients(env['MULTICA_MCP_CLIENTS'].strip(), default_workspaces)
        oauth_key = env.get('MULTICA_MCP_OAUTH_KEY_FILE', '').strip()
        if not clients and not oauth_key:
            raise ConfigError('нет клиентов: задайте MULTICA_MCP_KEY + MULTICA_PAT, MULTICA_MCP_CLIENTS '
                              'и/или MULTICA_MCP_OAUTH_KEY_FILE')
        public_url = (env.get('MULTICA_MCP_PUBLIC_URL', '').strip() or DEFAULT_PUBLIC_URL).rstrip('/')
        if not re.fullmatch(r'https?://[A-Za-z0-9.-]+(:\d+)?', public_url):
            raise ConfigError('MULTICA_MCP_PUBLIC_URL: нужен http(s)://хост[:порт] без пути')
        names = [c.name.lower() for c in clients]
        if len(set(names)) != len(names):
            raise ConfigError('имена клиентов не уникальны')
        if len({c.key for c in clients}) != len(clients):
            raise ConfigError('ключи клиентов не уникальны')
        state = env.get('STATE_DIRECTORY', '').split(':')[0] or env.get('MULTICA_MCP_STATE_DIR', '')
        if not state:
            raise ConfigError('STATE_DIRECTORY (systemd) или MULTICA_MCP_STATE_DIR не задан')
        port = int(env.get('MULTICA_MCP_PORT', '8101'))
        if not 1 <= port <= 65535:
            raise ConfigError('MULTICA_MCP_PORT вне диапазона')
        return cls(
            api_url=api_url, clients=tuple(clients), state_dir=Path(state),
            oauth_key_file=Path(oauth_key) if oauth_key else None, public_url=public_url,
            multica_bin=env.get('MULTICA_BIN', '/usr/local/bin/multica'), run_dir=env.get('MULTICA_MCP_RUN_DIR') or None,
            host=env.get('MULTICA_MCP_HOST', '127.0.0.1'), port=port,
            allowed_origins=_list(env.get('MULTICA_MCP_ALLOWED_ORIGINS')) or DEFAULT_ORIGINS,
            allowed_hosts=_list(env.get('MULTICA_MCP_ALLOWED_HOSTS')) or DEFAULT_HOSTS,
        )
