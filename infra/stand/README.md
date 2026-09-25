# stand

Стенды epus/frontend на ветку для агентов multica: `sudo stand up <имя> --ref <ветка> --wait`
собирает фронт в одноразовом контейнере и поднимает его на `https://<имя>.stand.yakutov.com`.

- `stand` — скрипт, на хосте агентов лежит в `/usr/local/bin/stand` (root:root 755),
  агентам разрешён через sudoers (`NOPASSWD: /usr/local/bin/stand`).
- `SKILL.md` — workspace-скилл multica `stand`, как агенты им пользуются.

## Ожидание

`stand wait` и `stand up --wait` блокируют до итога, но не дольше 540 с —
Bash-вызов агента ограничен 10 минутами. Код выхода: `0` — работает,
`1` — упал, `75` — ещё собирается (повторить `stand wait`). Последняя строка
вывода — `stand: <имя> running|failed|pending`. Если процесс сборки пропал
(перезагрузка, OOM), `wait` сам переводит стенд в `failed`, а не ждёт до упора.

## Выкладка

```bash
sudo install -m 755 -o root -g root infra/stand/stand /usr/local/bin/stand
multica skill update af53865b-5643-412d-81c9-b5f3f37c8244 --content-file infra/stand/SKILL.md
```
