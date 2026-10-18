"""Вызов root-входа из адаптеров: `sudo -n /usr/local/sbin/harness-priv <verb> … --json`, списком аргументов."""
import json
import os
import subprocess
from pathlib import Path

PRIV = '/usr/local/sbin/harness-priv'
SUDO = ['sudo', '-n']
NOT_INSTALLED_MARKERS = ('a password is required', 'is not allowed', 'may not run sudo', 'no tty present', 'command not found')
TIMEOUT = 120


def dumps(result):
    """Единый вид ответа для CLI и MCP."""
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)


def install_command():
    here = Path(__file__).resolve().parents[1] / 'bootstrap' / 'install.sh'
    where = str(here) if here.is_file() else '<каталог распакованного пакета>/bootstrap/install.sh'
    return f'оператор (root): sudo bash {where}'


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
