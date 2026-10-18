"""Доверенная проверка контракта CLI сторожа. Аргумент — каталог кандидата (только чтение).

Решение, включать ли таймер провайдеров, принимается по --capabilities, поэтому его формат — контракт.
"""
import json
import subprocess
import sys
from pathlib import Path

work = Path(sys.argv[1])
for name in ('multica-conveyor', 'control_state.py'):
    source = (work / name).read_text()
    compile(source, name, 'exec')  # без записи .pyc: каталог только для чтения

r = subprocess.run([sys.executable, '-I', str(work / 'multica-conveyor'), '--capabilities'],
                   capture_output=True, text=True, timeout=60, env={'PATH': '/usr/bin:/bin', 'MULTICA_CONVEYOR_CONFIG': '/nonexistent'})
assert r.returncode == 0, f'--capabilities завершился с кодом {r.returncode}: {r.stderr[-300:]}'
caps = json.loads(r.stdout)
assert isinstance(caps, dict), 'capabilities: ожидается объект'
lanes = caps.get('lanes')
assert isinstance(lanes, list) and all(isinstance(x, str) for x in lanes), 'capabilities.lanes: список строк'
assert 'epics' in lanes, 'полоса epics обязательна'
assert isinstance(caps.get('schema'), int), 'capabilities.schema: целое'
print('contract-smoke: ok', json.dumps(caps, sort_keys=True))
