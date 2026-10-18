# multica-conveyor

Исходники сторожа конвейера: `multica-conveyor` и общий модуль `control_state.py`.

## Что это

Один файл (stdlib, Python 3.12) с двумя полосами, каждая со своим run-lock:

- **epics** — приёмка и слияние веток эпиков, назначение следующей стадии, страница статуса.
  Запускает `multica-conveyor.timer` раз в 2 минуты.
- **providers** — смена модели агента на лимите и повтор задач. `multica-provider.timer` раз в минуту,
  `multica-conveyor --providers-only`. Таймер поставляется выключенным и включается по `--capabilities`.

`multica-conveyor --capabilities` печатает JSON `{"features": [...], "lanes": ["epics", "providers"], "schema": 1}`
и не читает конфиг.

`control_state.py` импортируют сторож, пульт `/opt/multica-control` и `subs-pick` (его зовёт старт каждого рана
claude/codex-reserve), поэтому на сервере три копии одного файла.

## Приёмка

Для задачи в `in_review`: свежий клон ветки, поверх свежий `base`, проверка диффа, команды `acceptance` эпика.
В конфиге эпика:

| ключ | смысл |
|---|---|
| `acceptance` | команды, по очереди, `shell=True` в клоне |
| `acceptance_timeout` | секунд на каждую команду (1500) |
| `acceptance_path` | `PATH` для команд; без него — как у юнита |
| `acceptance_env` | дополнительные переменные; значения вырезаются из лога дословно |

Полный лог (с редакцией токенов, права 0600) — `~/.local/state/multica-conveyor/accept/<задача>-<sha12>.log`,
старше 30 дней удаляется. В заголовке лога: `PATH` и имена переменных из `acceptance_env`. По таймауту группе процессов
команды шлётся TERM, через 5 с — KILL.

## Состояние

`~/.local/state/multica-conveyor/{state.json,providers-status.json,status/,accept/}`, управление — `controls.json`
пульта. Конфиг — `/etc/multica-conveyor.json`.

## Проверка

    python3 -I -m unittest discover -s tests -q

Тесты изолированы: Multica подменена, git — во временных каталогах, реальные агенты не запускаются.
Холостой прогон по боевому конфигу: `MULTICA_CONVEYOR_STATE=<копия state.json> multica-conveyor --dry-run`.

## Выкатка

Не руками: через `harness-control` (`services/harness-control`), компонент `multica-conveyor`. Он кладёт
`multica-conveyor` в `/usr/local/bin` и `control_state.py` в `/usr/local/bin` и `/opt/multica-control`, перезапускает
таймеры и проверяет следующий плановый тик. `systemd/` — копия юнитов на сервере; сами юниты ставит оператор.
