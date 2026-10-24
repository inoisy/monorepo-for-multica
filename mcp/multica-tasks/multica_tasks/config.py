"""Конфигурация целиком из окружения (EnvironmentFile юнита, права 0600). Неверная настройка — отказ на старте."""
import re
from dataclasses import dataclass
from pathlib import Path

MIN_KEY_LENGTH = 32
DEFAULT_ORIGINS = ('https://claude.ai', 'https://claude.com')
DEFAULT_HOSTS = ('multica.yakutov.com', '127.0.0.1', 'localhost')


class ConfigError(ValueError):
    pass


def _list(value):
    return tuple(x.strip() for x in (value or '').split(',') if x.strip())


@dataclass(frozen=True)
class Config:
    api_url: str
    pat: str = ''
    key: str = ''
    workspaces: tuple = ()
    state_dir: Path = Path('.')
    host: str = '127.0.0.1'
    port: int = 8101
    allowed_origins: tuple = DEFAULT_ORIGINS
    allowed_hosts: tuple = DEFAULT_HOSTS
    max_body: int = 1024 * 1024
    api_timeout: float = 20.0
    auth_fail_limit: int = 10
    auth_fail_window: float = 60.0

    @property
    def secrets(self):
        return tuple(s for s in (self.pat, self.key) if s)

    @classmethod
    def from_env(cls, env):
        def need(name):
            value = env.get(name, '').strip()
            if not value:
                raise ConfigError(f'{name} не задан')
            return value

        key = need('MULTICA_MCP_KEY')
        if len(key) < MIN_KEY_LENGTH:
            raise ConfigError(f'MULTICA_MCP_KEY короче {MIN_KEY_LENGTH} символов')
        api_url = need('MULTICA_API_URL').rstrip('/')
        if not re.fullmatch(r'https?://[A-Za-z0-9.-]+(:\d+)?', api_url):
            raise ConfigError('MULTICA_API_URL: нужен http(s)://хост[:порт] без пути')
        workspaces = _list(need('MULTICA_MCP_WORKSPACES'))
        if not workspaces:
            raise ConfigError('MULTICA_MCP_WORKSPACES: пустой список')
        state = env.get('STATE_DIRECTORY', '').split(':')[0] or env.get('MULTICA_MCP_STATE_DIR', '')
        if not state:
            raise ConfigError('STATE_DIRECTORY (systemd) или MULTICA_MCP_STATE_DIR не задан')
        port = int(env.get('MULTICA_MCP_PORT', '8101'))
        if not 1 <= port <= 65535:
            raise ConfigError('MULTICA_MCP_PORT вне диапазона')
        return cls(
            api_url=api_url, pat=need('MULTICA_PAT'), key=key, workspaces=workspaces, state_dir=Path(state),
            host=env.get('MULTICA_MCP_HOST', '127.0.0.1'), port=port,
            allowed_origins=_list(env.get('MULTICA_MCP_ALLOWED_ORIGINS')) or DEFAULT_ORIGINS,
            allowed_hosts=_list(env.get('MULTICA_MCP_ALLOWED_HOSTS')) or DEFAULT_HOSTS,
        )
