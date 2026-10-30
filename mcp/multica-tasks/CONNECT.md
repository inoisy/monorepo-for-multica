# Подключение к MCP Multica

Адрес: `https://multica.yakutov.com/mcp`. Подключение — как у остальных коннекторов: URL, вход в Multica в браузере, согласие.
Ключи, заголовки и шаги на сервере не нужны. Выкатку и однократную настройку делает владелец (`ROOT-STEPS.md`, шаг 10).

У сервера один инструмент `multica`: тот же CLI, что у агентов, с allowlist подкоманд. Действия в Multica идут от
вошедшего пользователя (его права и его имя в аудите), а не от общего пользователя. Вам доступны **все воркспейсы, где вы
состоите в Multica**, включая созданные позже; список настраивать не нужно, исключение из воркспейса закрывает доступ без
переподключения (список членства обновляется каждые 30 секунд).

## claude.ai (web и телефон)

Добавляется один раз в web-версии (или Desktop), после этого работает и в приложении на телефоне.

1. claude.ai → **Customize → Connectors** → **+ Add** → **Add custom connector**.
2. Имя: `Multica`. URL: `https://multica.yakutov.com/mcp`. Поля заголовков и OAuth Client ID/Secret не заполнять. **Add**.
3. **Connect** → откроется Multica. Если вы не вошли, войдите обычным способом (Google или код из письма); если уже вошли,
   сразу появится экран согласия: ваше имя, приложение и адрес возврата.
4. **Разрешить**. Вернётесь в claude.ai, коннектор в статусе подключён.
5. В чате: «+» внизу слева → **Connectors** → включить `Multica`.

На телефоне: коннектор, добавленный в web-версии, виден в приложении — достаточно включить его в чате. Если добавлять с телефона,
порядок тот же (меню → Connectors → Add custom connector); вход в Multica пройдёт в браузере телефона.

Запросы из claude.ai идут из облака Anthropic, а не с устройства: Мак при этом может спать. Названия пунктов меню Anthropic
иногда меняет; актуальный порядок:
https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

## Claude Code

```sh
claude mcp add --transport http multica https://multica.yakutov.com/mcp
```

Без `--header`, client ID и фиксированного порта. В сессии: `/mcp` → `multica` → **Authenticate** (или `claude mcp login multica`);
откроется браузер, войдите в Multica и разрешите доступ. Проверка: вызов `multica` с `{"args": ["issue", "get", "TST-123"]}`.
Адрес возврата для Claude Code — `http://localhost:<порт>/callback` с любым портом; сервис принимает только такой адрес
и callback `https://claude.ai/api/mcp/auth_callback`.

## Запасной путь: личный ключ (Bearer)

Прежний способ работает, пока владелец его не отключил: ключ сотрудника в `/etc/multica-tasks-mcp/clients.json`, заголовок
`Authorization: Bearer <ключ>`.

```sh
claude mcp add --transport http multica https://multica.yakutov.com/mcp --header "Authorization: Bearer <ключ>"
```

В claude.ai: **Add custom connector**, в **Request headers** — имя `Authorization`, значение `Bearer <ключ>`.

Ключ выдаёт владелец: сотрудник создаёт PAT в Multica (Settings → Tokens, 90 дней), передаёт его защищённым каналом, владелец
запускает `sudo bash /home/agents/ops/mcp-personal-keys/add-client.sh --name 'Имя' --workspaces stt` (или `--workspaces '*'` — все
воркспейсы владельца PAT, включая будущие), сотруднику передаётся ключ. Ключу только для чтения команды записи недоступны.

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

## Ошибки подключения

- `Could not resolve host` вместе с `connect … Operation not permitted`: сеть закрыта в sandbox Claude Code на Маке клиента,
  сервер ни при чём. Нужно разрешить в настройках sandbox Claude Code доступ к `multica.yakutov.com`.
- `401` при подключении через OAuth: срок подключения истёк или PAT отозван — подключитесь заново (в Claude Code `/mcp`
  → Authenticate; в claude.ai отключить и снова **Connect**). `401` для ключа: ключ неверный или заменён. `429`: больше 10 неверных попыток за минуту с адреса, подождать минуту.
- `-32602 workspace …`: вы не состоите в этом воркспейсе (или ключу он не разрешён); если воркспейсов несколько, укажите
  `workspace`. Только что созданный воркспейс виден в следующем вызове, переподключаться не нужно.
- Бесконечный переход между экраном входа и согласием: в браузере заблокированы cookie Multica для этого домена; откройте
  https://multica.yakutov.com в том же браузере, убедитесь, что вход выполнен, и повторите Connect.
- `429` на подключении: больше 20 регистраций клиента в час с одного адреса (у claude.ai общие адреса) — повторить позже.
- `isError` с `exit_code` ≠ 0: ошибка самого CLI (текст в `stderr`), например задача не найдена или нет прав у владельца PAT.

## Отзыв и срок действия (OAuth)

- При подключении сервис выпускает в Multica отдельный PAT «Claude MCP: <приложение> (<дата>)» на 90 дней и хранит его
  зашифрованным. Токен доступа живёт 15 минут, обновляется автоматически; срок подключения (grant) не продлевается обновлением,
  через 89 дней нужно подключиться заново.
- **Отключить доступ**: отозвать PAT «Claude MCP: …» в Multica (**Settings → Tokens**). Следующий запрос MCP и обновление токена
  получают отказ. Отключение коннектора в клиенте PAT в Multica
  **не удаляет** — отзовите его в настройках токенов, если он больше не нужен.
- **Срочно отключить всё**: владелец откатывает шаг 10 (`ROOT-STEPS.md`) или останавливает сервис MCP.
- Журнал: `/var/lib/multica-tasks-mcp/audit.jsonl`, поле `client` — имя вошедшего пользователя Multica (для ключа — имя клиента).

### Ротация ключей (запасной путь)

- **Личный ключ**: сгенерировать новый (`openssl rand -hex 32`), заменить в `clients.json`, перезапустить сервис, сотруднику
  выдать новый. Старый перестаёт работать сразу.
- **PAT ключа** живёт 90 дней: за неделю до конца сотрудник выпускает новый, владелец заменяет `token` в `clients.json`,
  перезапускает сервис, старый отзывается.
- **Отключить сотрудника по ключу**: убрать его строку из `clients.json`, перезапустить сервис, отозвать PAT в Multica.
