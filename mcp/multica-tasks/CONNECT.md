# Подключение к MCP Multica

Нужен готовый сервер (`ROOT-STEPS.md` выполнен) и ключ. Адрес: `https://multica.yakutov.com/mcp`. Вход — только по
Bearer-ключу в заголовке `Authorization`; IP-фильтра нет, ключ проверяет сам сервис.

У сервера один инструмент `multica`: тот же CLI, что у агентов, с allowlist подкоманд. Действия в Multica идут от
владельца ключа (его PAT), а не от общего пользователя.

## Claude Code (Mac сотрудника)

```sh
claude mcp add --transport http multica https://multica.yakutov.com/mcp --header "Authorization: Bearer <ключ>"
```

Проверка в сессии: вызов `multica` с `{"args": ["issue", "get", "TST-123"]}`.

## claude.ai (телефон, Desktop)

1. claude.ai → **Customize → Connectors** → **+ Add** → **Add custom connector**.
2. Имя: `Multica`. URL: `https://multica.yakutov.com/mcp`. **Continue**.
3. **Authentication**: **No sign in** (вход идёт ключом в заголовке, не OAuth).
4. **Request headers**: имя `Authorization`, значение `Bearer <ключ>`.
5. **Add**. В чате: «+» внизу слева → **Connectors** → включить `Multica`.

Запросы из claude.ai идут из облака Anthropic, а не с устройства: Мак при этом может спать. Названия пунктов меню Anthropic
иногда меняет; актуальный порядок:
https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

## Как вызывать

Аргументы инструмента `multica`: `args` (argv после имени бинаря, массив строк), `stdin` (текст до 256 КБ),
`workspace` (slug, имя или id; нужен, только если ключу разрешено больше одного). Ответ:
`{"exit_code", "stdout", "stderr", "truncated", "timeout"}`. `--output json` добавляется сам; справка — `--help` на любой
команде: `{"args": ["issue", "create", "--help"]}`.

```json
{"args": ["issue", "get", "TST-123"]}
{"args": ["issue", "comment", "add", "TST-123", "--content-stdin"], "stdin": "Текст комментария\nс переносами"}
{"args": ["issue", "create", "--title", "Заголовок", "--project", "Инструменты агентов", "--description-stdin"], "stdin": "## Зачем\n…"}
```

Многострочный текст — только через `stdin` и `--content-stdin` / `--description-stdin`: флаги `*-file`, `--allow-external-file`
и `--attach*` запрещены (читали бы файлы сервера).

## Что доступно

| Команды | Доступ |
|---|---|
| `issue` — чтение: list, get, search, children, pull-requests, timeline, runs, run-messages, usage; `comment`/`subscriber`/`label`/`property list`, `metadata list\|get`, `wakeup list\|get\|runs\|events` | да |
| `issue` — запись: create, update, assign, status, reorder, rerun-task, cancel-task, steer, model-profile, stages; `comment add\|update\|resolve\|unresolve`, `subscriber`/`label add\|remove`, `metadata set`, `property set\|unset`, `wakeup create\|update\|disable\|trigger\|checkin` | да, кроме ключей только для чтения |
| `project list\|get`, `agent list\|get\|models\|tasks`, `squad list\|get`, `squad member list`, `profile list`, `workflow list`, `label list`, `property list`, `skill list\|get`, `runtime unavailable`, `subscription list`, `workspace list`, `version` | чтение |
| удаление (`issue comment delete`, `issue metadata delete`, `issue wakeup delete`, любые `delete`), `agent models <агент> set\|profile\|personal\|single\|tools\|reset`, `runtime unavailable recheck`, `skill get --with-content` | нет |
| всё остальное (`agent create/update`, `skill create/update/delete`, `autopilot`, `pool`, `daemon`, `auth`, `config`, `repo`, `attachment`, …) и новые подкоманды CLI, пока их не внесли в таблицу | нет, только по ssh |

Отказ приходит как JSON-RPC ошибка `-32602` с текстом «только по ssh»; процесс не запускается, отказ пишется в аудит.

## Ловушки CLI (в `--help` их нет)

- `issue create --assignee`, `issue update --assignee` и `issue assign --to` **сразу стартуют ран**.
- `issue create` в проект с лидом-агентом **без** `--assignee` всё равно назначает лида и стартует ран.
- `issue comment add` будит исполнителя.
- Снять исполнителя можно только так: `issue assign <KEY> --unassign`.
- `issue cancel-task` принимает полный UUID рана: `issue runs <KEY> --full-id`.

## Личный ключ сотруднику (шаг владельца)

1. Сотрудник входит в Multica и создаёт PAT (Settings → Tokens), срок 90 дней. Передаёт его владельцу защищённым каналом.
2. Владелец на сервере по `ROOT-STEPS.md`, шаг «Личные ключи», генерирует ключ и добавляет строку в
   `/etc/multica-tasks-mcp/clients.json`, затем перезапускает сервис. Ключ показывается один раз, его передают сотруднику.
3. Сотрудник выполняет `claude mcp add …` из раздела выше со своим ключом.

## Ошибки подключения

- `Could not resolve host` вместе с `connect … Operation not permitted`: сеть закрыта в sandbox Claude Code на Маке клиента,
  сервер ни при чём. Нужно разрешить в настройках sandbox Claude Code доступ к `multica.yakutov.com`.
- `401`: ключ неверный или заменён. `429`: больше 10 неверных попыток за минуту с адреса, подождать минуту.
- `-32602 workspace …`: ключу разрешены другие воркспейсы или их несколько и нужно указать `workspace`.
- `isError` с `exit_code` ≠ 0: ошибка самого CLI (текст в `stderr`), например задача не найдена или нет прав у владельца PAT.

## Ротация и отзыв

- **Личный ключ**: сгенерировать новый (`openssl rand -hex 32`), заменить в `clients.json`, перезапустить сервис,
  сотруднику выдать новый. Старый перестаёт работать сразу.
- **PAT** живёт 90 дней. За неделю до конца сотрудник выпускает новый, владелец заменяет `token` в `clients.json`,
  перезапускает сервис, старый отзывается. То же для `MULTICA_PAT` клиента по умолчанию.
- **Отключить сотрудника**: убрать его строку из `clients.json`, перезапустить сервис, отозвать PAT в Multica.
- **Срочно отключить всё**: остановить сервис MCP и отозвать PAT. Остальное это не затрагивает.
- Журнал: `/var/lib/multica-tasks-mcp/audit.jsonl`, поле `client` — чьим ключом сделан вызов.
