"""Доверенная проверка canary: скрипт кандидата запускается и пишет статус нужного вида. Аргумент — каталог кандидата."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

work = Path(sys.argv[1])
with tempfile.TemporaryDirectory() as state:
    r = subprocess.run([sys.executable, '-I', str(work / 'canary.py')], capture_output=True, text=True, timeout=60,
                       env={'STATE_DIRECTORY': state, 'PATH': '/usr/bin:/bin'})
    version = (work / 'VERSION').read_text().strip()
    status = json.loads((Path(state) / 'status.json').read_text())
    assert set(status) >= {'tick', 'version', 'errors'}, f'в статусе нет обязательных ключей: {sorted(status)}'
    assert status['version'] == version, 'версия в статусе не совпадает с VERSION'
    assert r.returncode == (1 if 'fail' in version else 0), f'код выхода {r.returncode} для версии {version}'
print('canary-smoke: ok')
