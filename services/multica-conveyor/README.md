# multica-conveyor — сторож конвейера эпиков

Исходники установленного сторожа. На сервере: `/usr/local/bin/multica-conveyor` и `/usr/local/bin/control_state.py`
(root, копия отсюда), конфиг `/etc/multica-conveyor.json`, запуск — `multica-conveyor.timer` раз в 2 минуты
от пользователя `agents`; пульт — `/opt/multica-control` (тот же `control_state.py`).

## Кто владеет вливанием

Сторож принимает `in_review`, вливает ветку и запускает следующий пакет только если в эпике явно задано
`"coordinator": "external"` и `base` — не `main`/`master`. Иначе он только наблюдает: пишет снимок для
страницы статуса, ничего не назначает, не вливает, не повторяет. Так человек (`dev → main`) и Тимлид
(приёмка в `dev`) не конкурируют со сторожем за одну и ту же задачу.

## Защита от повторов и гонок

- один процесс на тик (`state.run.lock`); пересечение тиков пропускается;
- состояние пишется атомарно (temp + fsync + rename), битое состояние останавливает действия;
- назначение — одна запись `issue update --assignee-id … --status todo`; до записи в состоянии
  `_dispatch[ключ]=pending`, после — `confirmed`; неизвестный исход не повторяется автоматически;
- активный ран (в т.ч. `waiting_local_directory`) или включённый будильник у любой задачи эпика
  блокируют новый запуск и приёмку; задача с `Ждёт:` в начале строки не запускается;
- перед слиянием и переводом в `done` задача перечитывается: ветки и base те же, статус `in_review`.

## Проверка

    python3 -I -m unittest discover -s tests -v

Тесты изолированы: Multica подменена, git — во временных каталогах, реальных записей нет.
Холостой прогон по боевому конфигу: `MULTICA_CONVEYOR_STATE=<копия state.json> multica-conveyor --dry-run`.

## Установка и откат (нужен root)

    sudo install -m 755 multica-conveyor /usr/local/bin/multica-conveyor
    sudo install -m 644 control_state.py /usr/local/bin/control_state.py
    sudo install -m 644 control_state.py /opt/multica-control/control_state.py
    sudo systemctl restart multica-control

Откат: те же команды с файлами из коммита, предшествующего правке (`git show <коммит>^:…`).
Перед установкой убедиться, что цель на пульте стоит на паузе или `systemctl is-active multica-conveyor.service`
показывает `inactive` — идущий тик не прерывать.
