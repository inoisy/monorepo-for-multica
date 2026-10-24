"""Сборка и запуск: конфигурация из окружения → сервер. Ключ и PAT в логи не пишутся."""
import json
import logging
import os
import signal
import sys
import threading

from .api import Api
from .audit import AuditLog
from .config import Config, ConfigError
from .http import make_server
from .service import Service


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {'level': record.levelname, 'logger': record.name, 'message': record.getMessage()}
        entry.update(getattr(record, 'ctx', {}))
        if record.exc_info:
            entry['exception'] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(entry, ensure_ascii=False)


def main(env=None):
    env = os.environ if env is None else env
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    log = logging.getLogger('multica_tasks')
    try:
        config = Config.from_env(env)
    except (ConfigError, ValueError) as e:
        log.error('конфигурация: %s', e)
        return 2
    config.state_dir.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(config.state_dir / 'audit.jsonl', config.secrets)
    api = Api(config.api_url, config.pat, config.api_timeout, config.secrets)
    server = make_server(config, Service(api, config.workspaces, audit))
    # shutdown() блокируется до выхода из serve_forever: из обработчика сигнала зовём его в отдельном потоке
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    log.info('слушаю %s:%s', config.host, config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
