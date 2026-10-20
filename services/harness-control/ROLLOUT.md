# Снятие control-state

Пакет harness-control только с `harness-canary`. Компонент `control-state` (общий модуль подписок `control_state.py`)
снят: после этапа B подписок (20.10.2026) подписки живут в multica, `/usr/local/bin/subs-pick` удалён, пульт
`multica-control` выключен (`disable`). Модуль больше никто не импортирует, а health компонента («subs-pick выбирает
подписку») был всегда красным. Ставится после этапа B.

До него этот файл описывал выкладку `control-state` вместо сторожа конвейера (`multica-conveyor`) — см. историю git.

## Проверка перед выкладкой

```sh
python3 -I -m unittest discover -s services/harness-control/tests -q
```

На хосте убедиться, что модуль никто не импортирует:

```sh
grep -rlE 'import control_state|from control_state' /usr/local/bin /usr/local/lib /opt /home/agents/.local/bin 2>/dev/null
systemctl is-enabled multica-control.service    # disabled
```

## Шаги

1. Оператор: бэкап `/etc/harness-control`, `/usr/local/lib/harness-control`, `/var/lib/harness-control`; затем
   `bash services/harness-control/bootstrap/build-release.sh <коммит>`, `install.sh --check`, `install.sh --upgrade`.
   Обновление снимает `/etc/harness-control/policy.d/{multica-conveyor,control-state}.json` и
   `/usr/local/lib/harness-control/checks/{multica-conveyor,control-state}/`.
2. `harness-control inspect`: в списке только `harness-canary` (её health красный, пока таймер выключен).
3. Файлы `/usr/local/bin/control_state.py` и `/opt/multica-control/` не трогаются — они нужны `rollback.sh` этапа B
   (`/var/backups/multica-subs-b.<время>/`).

## Откат

`install.sh --upgrade` прежнего пакета возвращает политику и проверки `control-state`; baseline компонента в
`/var/lib/harness-control` установщик не удаляет.
