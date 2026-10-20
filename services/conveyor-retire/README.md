# conveyor-retire

Снятие сторожа конвейера (`multica-conveyor`) с сервера: этап 4 ТЗ `docs/stt/tz-conveyor-in-multica.md` в форке
multica. Всё, что делал сторож, теперь в multica: маршрут задачи, приёмка и слияние (шаг `accept`), стадии эпика
(`multica issue stages`), повтор после квоты и сбоев связи. Загрузку справочников стендов делает `stand-seed`
(`services/stand`).

## Порядок

Только после того, как в multica выкачены шаг `accept` и серверные стадии и сквозная проверка на стенде прошла.

1. Сухой прогон переноса — от пользователя `agents` (у него `multica` и токен):

   ```sh
   services/conveyor-retire/epics-to-stages --out /tmp/conveyor-retire
   ```

2. Перенос: `… --apply`. Включает серверное назначение стадий у эпиков, ставит `waiting` задачам с «**Ждёт:**»,
   пишет черновики `.multica/acceptance.json` по репозиториям и `stand-seed.json`. Черновики приёмки — коммитом в
   репозитории (с review); имена `acceptance_env` — в окружение демонов с runtime `accept`; `stand-seed.json` — в
   `/etc/stand/seed.json`, затем `systemctl enable --now stand-seed.timer`. Отчёт в конце — что сделать руками.
3. Снятие с хоста (root): `retire-host --check`, затем `retire-host`. Снимает таймеры и юниты сторожа, полосы
   провайдеров и `multica-fallback`, файлы `multica-conveyor`, `mconv`, `multica-fallback`, `/etc/multica-conveyor.json`
   — всё в `/var/backups/conveyor-retire.<время>/` с `rollback.sh`. `control_state.py` и `subs-pick` остаются.
   Пульт `multica-control` остаётся (держит подписки); `--with-pult` останавливает и его.
4. `harness-control` обновить пакетом с компонентом `control-state` (`install.sh --upgrade` снимает политику
   `multica-conveyor`).

## Откат

`sudo /var/backups/conveyor-retire.<время>/rollback.sh` возвращает файлы и включает то, что было включено; затем
`multica issue stages <эпик> --off` для эпиков, которые снова ведёт сторож.

Проверка: `python3 -I -m unittest discover -s tests -q` (корень и systemctl подменены, multica — фальшивый).
