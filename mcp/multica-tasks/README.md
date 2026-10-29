# multica-tasks

Удалённый MCP-сервер Multica. Claude (claude.ai, телефон, Desktop) и Claude Code на Маках сотрудников через него работают
с задачами и ранами Multica. Один инструмент `multica`: тот же CLI, что у агентов на сервере, с allowlist подкоманд и
личным токеном клиента.

Сервер не содержит логики задач: он проверяет команду по allowlist, подставляет токен владельца ключа, запускает CLI без
shell и пишет аудит. Документация по командам — `--help` самого CLI и скилл `multica`. Ничего не деплоит и не удаляет.

Python 3.12, только stdlib. Установка и подключение: `ROOT-STEPS.md` (оператор) и `CONNECT.md` (пользователь).

## Инструмент `multica`

| Аргумент | Тип | Смысл |
|---|---|---|
| `args` | массив строк, обязателен | argv после имени бинаря, например `["issue","get","TST-123"]`; без shell, символы `;`, `$(`, `\|` — обычный текст |
| `stdin` | строка до 256 КБ | для `--content-stdin` и `--description-stdin`; без stdin процесс получает пустой ввод |
| `workspace` | строка | slug, имя или id; обязателен, если ключу разрешено больше одного воркспейса |

Ответ: `{"exit_code", "stdout", "stderr", "truncated", "timeout"}`. Код выхода ≠ 0 и таймаут дают `isError: true`.

- **Запуск.** `subprocess` с argv, `cwd` — пустой временный каталог (`MULTICA_MCP_RUN_DIR`), окружение только
  `MULTICA_TOKEN`, `MULTICA_SERVER_URL`, `MULTICA_WORKSPACE_ID`, `HOME` (равен `cwd`), `PATH`. Таймаут 30 с, затем kill
  группы процессов, `exit_code=null`, `timeout=true`. Не больше 4 запусков одновременно.
- **Вывод.** stdout и stderr по 64 КБ, обрезка с пометкой и `truncated: true`. Секреты маскируются до обрезки, поэтому
  ключ или токен на границе не утекают половиной.
- **`--output json`** добавляется, если в `args` нет `--output`, нет `--help`/`-h` и это не `version`. Подкоманда без этого
  флага (`unknown flag: --output`) запускается повторно без него: флаг разбирается до действия.
- **Воркспейс.** Список воркспейсов ключа берётся один раз `workspace list` его же токеном; `MULTICA_WORKSPACE_ID` ставится
  по разрешённому списку. `workspace list`, `version` и `--help` воркспейса не требуют.

### Allowlist

Единственная таблица — `COMMANDS` в `multica_tasks/policy.py`: явный перечень путей команд с отметкой «чтение» или
«запись»; тест проверяет каждую строку. Всё, чего нет в таблице, — JSON-RPC `-32602` с текстом «только по ssh», процесс не
запускается, отказ идёт в аудит. Новая подкоманда CLI через MCP недоступна, пока её не внесут в таблицу. Путь команды —
слова до первого флага: `issue --output json comment delete` не совпадает ни с одной строкой.

| Команды | Доступ |
|---|---|
| `issue list\|get\|search\|children\|pull-requests\|timeline\|runs\|run-messages\|usage`, `issue comment\|subscriber\|label\|property list`, `issue metadata list\|get`, `issue wakeup list\|get\|runs\|events` | чтение |
| `issue create\|update\|assign\|status\|reorder\|rerun-task\|cancel-task\|steer\|model-profile\|stages`, `issue comment add\|update\|resolve\|unresolve`, `issue subscriber\|label add\|remove`, `issue metadata set`, `issue property set\|unset`, `issue wakeup create\|update\|disable\|trigger\|checkin` | запись |
| `project list\|get`, `agent list\|get\|models\|tasks`, `squad list\|get`, `squad member list`, `profile list`, `workflow list`, `label list`, `property list`, `skill list\|get`, `runtime unavailable`, `subscription list`, `workspace list`, `version` | чтение; у `agent models` запрещены `set`, `profile`, `personal`, `single`, `tools`, `reset`; `skill get --with-content` и `runtime unavailable recheck` запрещены |
| `--help`, `-h` | на любой разрешённой команде и группе |

Удаления нет совсем: `issue comment delete`, `issue metadata delete`, `issue wakeup delete` и любые `delete` других групп
запрещены. Ключу с `read_only` доступны только строки «чтение» и справка.

Запрещены везде: флаги `*-file` (`--content-file`, `--description-file`, `--instruction-file`, `--allow-external-file`) и
`--attach*` — они читают файлы сервера; глобальные `--server-url`, `--profile`, `--workspace-id`, `--debug` — увели бы токен
на чужой адрес. Запрещены группы `agent` на запись (create/update/archive, env, mcp, skills), `skill` на запись, `autopilot`,
`pool`, `subscription` кроме `list`, `runtime` кроме `unavailable`, `daemon`, `auth`, `login`, `setup`, `config`, `update`,
`user`, `attachment`, `repo`, `project`/`property`/`label`/`profile`/`workflow` на запись, `workspace` кроме `list`.

## Клиенты и ключи

- **Клиент по умолчанию** «Claude (MCP)»: `MULTICA_MCP_KEY` + `MULTICA_PAT` (claude.ai Евгения), воркспейсы из `MULTICA_MCP_WORKSPACES`.
- **Личные ключи**: файл `MULTICA_MCP_CLIENTS` (путь из env, JSON, права 0600, владелец — пользователь сервиса):
  `[{"name": "Илья", "key": "…", "token": "mul_…", "workspaces": ["stt"], "read_only": false}]`. `read_only: true` — ключ
  только для чтения (для клиента по умолчанию — `MULTICA_MCP_READ_ONLY=true`). Ключ входа → собственный PAT человека, действия
  в Multica идут от него. Имена и ключи уникальны, ключ от 32 символов. Сервис не стартует, если файл доступен группе или
  всем. Файл читается на старте: после правки сервис перезапускают.
- Ключ ищется среди всех клиентов без раннего выхода (`hmac.compare_digest`). Перебор: 10 неверных попыток за минуту с адреса
  дают 429 (адрес клиента — последний элемент `X-Forwarded-For`, и только с loopback).

## Безопасность

- **Вход.** `POST /mcp` с `Authorization: Bearer <ключ>`. Порядок отказов: путь (404), `Host` (403), `Origin` (403), перебор
  (429), ключ (401), размер (413 при теле больше 1 МБ). `GET /mcp` — 405. Без сессий и SSE. Неизвестный
  `MCP-Protocol-Version` — 400 до вызова инструмента.
- **Периметр.** IP-фильтра в Caddy нет: ключ проверяет сам сервис (`deploy/Caddyfile.fragment`).
- **Права в Multica.** Определяет PAT: сервис ничего не расширяет, но и не сужает сверх allowlist. Токен идёт только в
  `MULTICA_TOKEN` процесса и не попадает в аргументы.
- **Маскирование** (`redaction.py`): ключи и PAT всех клиентов вырезаются из stdout, stderr, сообщений об ошибках и аудита.
- **Аудит** — `$STATE_DIRECTORY/audit.jsonl`, 0600, строка на каждый вызов: `client`, `client_ip`, `argv`, `exit_code`,
  `timeout`, `duration`, `stdin_length`, `stdout_length`, `denied`. У `stdin` — sha256, длина и первые 200 символов после
  маскирования. `denied` — причина отказа allowlist (при отказе `exit_code=null`), иначе `null`.
- **Юнит** от пользователя `multica-mcp`: `ProtectSystem=strict`, `NoNewPrivileges`, пустой `CapabilityBoundingSet`,
  `MemoryMax=256M`, слушает только `127.0.0.1:8101`.

## Конфигурация

Только из окружения (`/etc/multica-tasks-mcp/env`, 0600), пример — `deploy/env.example`. Нужен хотя бы один клиент
(`MULTICA_MCP_KEY` + `MULTICA_PAT` и/или `MULTICA_MCP_CLIENTS`), `MULTICA_API_URL` (адрес бэкенда для CLI), `STATE_DIRECTORY`
(задаёт systemd). Неверная настройка — выход с кодом 2 до открытия порта.

## Тесты

```sh
python3 -I -W error::ResourceWarning -m unittest discover -s mcp/multica-tasks/tests
```

CLI подменяется фейковым скриптом (`tests/support.py`: пишет argv, окружение и stdin вызова), HTTP-обмен идёт через
`socketpair`, поэтому тесты работают в песочнице без сети. Два теста настоящего процесса на TCP там пропускаются.
Вручную: `MULTICA_BIN=<фейк> MULTICA_MCP_PORT=… python3 -I bin/multica-tasks-mcp`, затем `curl -i -X POST localhost:<порт>/mcp`
(401), с ключом клиента и `{"method":"tools/list"}` (200).

## Выкладка

Образ собирается из `Dockerfile` (бинарь `multica` берётся из образа backend, тег закреплён в `ARG MULTICA_BACKEND_IMAGE`: при обновлении платформы поднять его); подготовка перехода на compose: `compose.yaml` для
изолированного стенда, `deploy/compose.production.yaml` для действующего проекта.
Переключение и откат — `services/harness-retire/README.md` от корня репозитория.
После переключения MCP обновляется и откатывается вместе с платформой через
`multica-autodeploy`: версия образа закреплена файлом `deploy/autodeploy/mcp-image`
в форке. До проверки замены действующую службу и прежний механизм не снимать.

До переключения действует прежняя установка по `ROOT-STEPS.md` и обновления через harness-control, компонент
`multica-tasks-mcp`: `validate` на коммит из `main`, `deploy`, health `GET http://127.0.0.1:8101/healthz`, при провале
автооткат. Политика: `services/harness-control/policy.d/multica-tasks-mcp.json`, доверенная проверка:
`services/harness-control/checks/multica-tasks-mcp/`.

## Чего нет

- Удаления задач и любых сущностей, правки инструкций, env, навыков и MCP агентов, токенов, секретов, deploy/rollback.
- OAuth: ключ в заголовке. OAuth понадобится, если коннектор придётся отдавать посторонним.
- Поведение платформы «статус → `todo` не будит агента» не меняется. Ловушки CLI (какая команда стартует ран) описаны в `CONNECT.md`.
- Воркспейс со slug `mcp` становится недоступен по пути `/mcp` на этом домене.
