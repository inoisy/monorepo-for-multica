"""Доверенная проверка: установленный subs-pick работает с control_state кандидата.

subs-pick вызывает старт каждого рана claude/codex-reserve; битый control_state остановил бы запуск агентов.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

work = Path(sys.argv[1])
installed = Path('/usr/local/bin/subs-pick')
assert installed.is_file(), 'subs-pick не установлен'
with tempfile.TemporaryDirectory() as tmp:
    shutil.copy(installed, Path(tmp) / 'subs-pick')
    shutil.copy(work / 'control_state.py', Path(tmp) / 'control_state.py')
    r = subprocess.run([sys.executable, str(Path(tmp) / 'subs-pick'), '--decide',
                        '{"order": "first", "subs": [{"id": "a", "state": null, "caps": {}}, {"id": "b", "state": null, "caps": {}}]}'],
                       capture_output=True, text=True, timeout=60, env={'PATH': '/usr/bin:/bin', 'HOME': tmp})
assert r.returncode == 0, f'subs-pick завершился с кодом {r.returncode}: {r.stderr[-300:]}'
assert r.stdout.strip() in ('a', 'b'), f'subs-pick выбрал {r.stdout.strip()!r}'
print('subs-pick-smoke: ok')
