# Выкладка control-state и снятие сторожа

Пакет harness-control с компонентом `control-state` вместо `multica-conveyor`. Ставится после того, как сторож снят
(`services/conveyor-retire/README.md`): до снятия сторож и его таймеры продолжают жить на прежней политике.

## Проверка перед выкладкой

```sh
python3 -I -m unittest discover -s services/control-state/tests -q
python3 -I services/harness-control/checks/control-state/state_compat.py services/control-state
python3 -I services/harness-control/checks/control-state/subs_pick_smoke.py services/control-state   # на хосте с subs-pick
python3 -I -m unittest discover -s services/harness-control/tests -q
```

`control_state.py` перенесён из `services/multica-conveyor` без изменений: установленный модуль и кандидат совпадают
побайтно, выкладка ничего не меняет в работе `subs-pick` и пульта.

## Шаги

1. Оператор: `bash services/harness-control/bootstrap/build-release.sh <коммит>`, `install.sh --check`, затем
   `install.sh --upgrade`. Обновление снимает `/etc/harness-control/policy.d/multica-conveyor.json` и записывает
   baseline `control-state` из установленных файлов.
2. `harness-control inspect control-state`: политика, drift (должен быть чистым), health.
3. Дальнейшие правки модуля — обычным путём: `validate control-state <sha40>` → `deploy … --validation … --digest …`.
   Изменение `/opt/multica-control/control_state.py` перезапускает пульт.

## Откат

`install.sh` прежнего пакета (`--upgrade`) возвращает политику `multica-conveyor`; файлы сторожа возвращает
`rollback.sh` из `/var/backups/conveyor-retire.<время>/`.
