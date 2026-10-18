"""Доверенная проверка совместимости state.json и controls.json: кандидат читает прежние файлы и ничего не теряет."""
import importlib.machinery
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

work, here = Path(sys.argv[1]), Path(__file__).resolve().parent
sys.path.insert(0, str(work))
import control_state  # noqa: E402

controls = json.loads((here / 'fixtures' / 'controls.json').read_text())
state = json.loads((here / 'fixtures' / 'state.json').read_text())

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / 'controls.json'
    path.write_text(json.dumps(controls))
    with control_state.Store(path).locked() as current:
        assert current == controls, 'Store прочитал controls.json иначе, чем он записан'
        current['_probe'] = 1
    after = json.loads(path.read_text())
    assert after == {**controls, '_probe': 1}, 'Store потерял или исказил ключи controls.json'

    loader = importlib.machinery.SourceFileLoader('conveyor', str(work / 'multica-conveyor'))
    spec = importlib.util.spec_from_loader('conveyor', loader)
    conveyor = importlib.util.module_from_spec(spec)
    loader.exec_module(conveyor)
    state_path = Path(tmp) / 'state' / 'state.json'
    state_path.parent.mkdir()
    state_path.write_text(json.dumps(state))
    conveyor.STATE = state_path
    watch = conveyor.Watch(True)
    assert watch.state == state, 'Watch прочитал state.json иначе, чем он записан'
print('state-compat: ok')
