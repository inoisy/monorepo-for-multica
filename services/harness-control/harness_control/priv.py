"""Root-вход. Разбирает аргументы по таблице глаголов, передаёт Harness.handle, печатает JSON.

Исполняется только как /usr/local/sbin/harness-priv (root через sudoers) или от оператора. Окружение не доверяется:
из него берутся только SUDO_USER, MULTICA_AGENT_NAME и MULTICA_TASK_ID — для аудита.
"""
import json
import os
import sys

from . import client
from .commands import COMMANDS, parse
from .core import ADMIN_VERBS, Harness, clean_actor
from .errors import HarnessError
from .paths import Paths


def syslog_logger():
    import logging
    import logging.handlers
    try:
        handler = logging.handlers.SysLogHandler(address='/dev/log')
    except OSError:
        return None
    log = logging.getLogger('harness-control')
    handler.setFormatter(logging.Formatter('harness-control: %(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log.info


def main(argv, env=None, out=sys.stdout, system=None, spawn=None):
    env = os.environ if env is None else env
    if not argv:
        out.write(client.dumps({'error': 'bad_request', 'reason': 'нужен глагол', 'missing': None}) + '\n')
        return 2
    verb, tokens = argv[0], argv[1:]
    try:
        if verb in ADMIN_VERBS:
            args = {'component': tokens[0]} if tokens and verb == 'adopt-baseline' else {'id': tokens[0]} if tokens and verb == 'run-op' else {}
        elif verb in COMMANDS:
            args = parse(verb, tokens)
        else:
            raise HarnessError('verb_not_allowed', f'неизвестное действие {verb[:40]!r}')
        harness = Harness(Paths.from_env(), system=system, spawn=spawn, audit_logger=syslog_logger(),
                          owner=None if os.geteuid() == 0 else _current_owner())
        result = harness.handle(verb, args, clean_actor(env))
    except HarnessError as e:
        result = e.to_dict()
    except Exception as e:  # состояние недоступно, БД повреждена и т.п.: отказ в том же формате, а не traceback
        result = HarnessError('internal', f'{type(e).__name__}: {str(e)[:300]}').to_dict()
    out.write(client.dumps(result) + '\n')
    return 1 if 'error' in result else 0


def _current_owner():
    from .activate import Owner
    return Owner(os.getuid(), os.getgid())
