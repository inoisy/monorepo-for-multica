"""Доверенная проверка совместимости controls.json: кандидат читает прежний файл и ничего не теряет."""
import json
import sys
import tempfile
from pathlib import Path

work, here = Path(sys.argv[1]), Path(__file__).resolve().parent
sys.path.insert(0, str(work))
import control_state  # noqa: E402

controls = json.loads((here / 'fixtures' / 'controls.json').read_text())

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / 'controls.json'
    path.write_text(json.dumps(controls))
    with control_state.Store(path).locked() as current:
        assert current == controls, 'Store прочитал controls.json иначе, чем он записан'
        current['_probe'] = 1
    after = json.loads(path.read_text())
    assert after == {**controls, '_probe': 1}, 'Store потерял или исказил ключи controls.json'
print('state-compat: ok')
