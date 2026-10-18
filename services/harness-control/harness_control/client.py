"""Вызов root-входа из адаптеров: `sudo -n /usr/local/sbin/harness-priv <verb> … --json`, списком аргументов."""
import json
import os
import subprocess

PRIV = '/usr/local/sbin/harness-priv'
SUDO = ['sudo', '-n']
NOT_INSTALLED_MARKERS = ('a password is required', 'is not allowed', 'may not run sudo', 'no tty present', 'command not found')
TIMEOUT = 120


def dumps(result):
    """Единый вид ответа для CLI и MCP."""
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)


def is_error(result):
    """У операции ключ error есть и при успехе; отказом считается только заполненная ошибка."""
    return bool(result.get('error'))


def install_command():
    # Путь не берётся рядом с адаптером: из рабочего каталога агента он указал бы оператору на файл, который агент может менять.
    return ('оператор (root): собрать пакет из проверенного коммита (bootstrap/build-release.sh), сверить SHA256, '
            'распаковать в каталог root и выполнить sudo bash <пакет>/bootstrap/install.sh')


def unknown_verb(verb):
    """Отказ на глагол вне таблицы (в том числе административный): одинаковый у CLI и MCP."""
    return {'error': 'verb_not_allowed', 'reason': f'неизвестное действие {str(verb)[:40]!r}',
            'missing': 'действия оператора (adopt-baseline, recover) агенту недоступны'}


def not_installed(reason):
    return {'error': 'not_installed', 'reason': reason, 'missing': install_command()}


def call(verb, tokens, run=subprocess.run, priv=PRIV, exists=os.path.exists):
    if not exists(priv):
        return not_installed(f'{priv} не установлен: harness-control ещё не поставлен оператором')
    try:
        r = run([*SUDO, priv, verb, *tokens, '--json'], capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {'error': 'internal', 'reason': f'harness-priv не ответил за {TIMEOUT} с', 'missing': None}
    try:
        result = json.loads(r.stdout)
        if isinstance(result, dict):
            return result
    except ValueError:
        pass
    stderr = (r.stderr or '').strip()
    if any(m in stderr for m in NOT_INSTALLED_MARKERS):
        return not_installed(f'sudo не разрешает запускать {priv}: {stderr.splitlines()[-1][:200] if stderr else ""}')
    return {'error': 'internal', 'reason': f'harness-priv завершился с кодом {r.returncode}: {stderr[-300:] or "нет вывода"}', 'missing': None}
