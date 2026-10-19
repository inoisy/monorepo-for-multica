# control-state

`control_state.py` — общий модуль подписок: таблицы подписок и квот, окна, выбор аккаунта, перевод запретов
инструментов между семействами CLI. Его импортируют `subs-pick` (старт каждого рана claude/codex-reserve) и пульт
`multica-control`.

Раньше лежал рядом со сторожем конвейера (`services/multica-conveyor`); сторож снят (маршрут, приёмка, стадии и
повторы — в multica), модуль остался и выкатывается своим компонентом `harness-control` — `control-state`
(`/usr/local/bin/control_state.py`, `/opt/multica-control/control_state.py`, перезапуск пульта при изменении).

Проверка: `python3 -I -m unittest discover -s tests -q`.
