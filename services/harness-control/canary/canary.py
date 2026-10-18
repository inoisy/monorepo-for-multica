#!/usr/bin/python3 -I
"""Тестовый компонент harness-control: раз в минуту пишет статус с версией и временем тика."""
import datetime as dt
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def version(directory=HERE):
    return (Path(directory) / 'VERSION').read_text().strip()


def run(directory=HERE, state_dir=None, now=None):
    """Пишет status.json и возвращает код выхода. Версия с «fail» нужна, чтобы проверить автооткат."""
    state_dir = Path(state_dir or os.environ.get('STATE_DIRECTORY', '/var/lib/harness-canary'))
    now = now or dt.datetime.now(dt.timezone.utc)
    ver = version(directory)
    errors = [f'версия {ver} помечена как сбойная'] if 'fail' in ver else []
    status = {'tick': now.strftime('%Y-%m-%d %H:%M:%S'), 'version': ver, 'errors': errors}
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / 'status.json.tmp'
    tmp.write_text(json.dumps(status, ensure_ascii=False))
    os.chmod(tmp, 0o644)
    tmp.replace(state_dir / 'status.json')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(run())
