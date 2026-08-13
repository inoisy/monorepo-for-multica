# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sphere-integration** — TypeScript MCP-сервер для работы с задачами Bitrix24 (аналог Jira) на `https://sphere.loodsen.ru`. Разворачивается на сервере для всех сотрудников.

**Единственный режим доступа:** API mode — Bitrix24 REST API через webhook (`B24_WEBHOOK_URL`). Batch-запросы, никаких браузеров.

**Browser mode** — legacy, лежит в `src/legacy/`. Требует VPN + Keycloak SSO. Не используется в production.

Цель — извлекать задачи со статусом "Открыто" или "В работе", собирая полный контекст: описание, комментарии, родительская Story, связанные бэкенд-задачи.

## Design Principles

- **Никакого кеширования** — данные всегда живые из API, никакого fs storage
- **Никакого base64** — агенты никогда не получают base64 в ответе. Картинки — это ссылки на Bitrix URL
- **Read-only по умолчанию** — `MCP_WRITE_ENABLED=false` (env), write-операции требуют явного включения
- **stdout чистый** — MCP server пишет логи в stderr, stdout только JSON-RPC

## Commands

```bash
npm install                      # Install deps

# API mode — извлечение задач (основной):
tsx src/cli.ts fetch-my-tasks-api [--no-context] [--with-siblings] [--all-stages] [--stage <id1,id2>]

# MCP server:
node dist/mcp-server.js                       # Запуск MCP сервера (stdin/stdout)

# Webhook server:
tsx src/cli.ts webhook                        # HTTP server на порту 3100

npm run typecheck                # Type-check без сборки
npm run build                    # Compile в dist/
npm run mcp:inspect             # Запуск MCP Inspector (port 6270)
```

Тесты: `npm test` — vitest (`src/**/*.test.ts`).

## Architecture

### Pipeline (API mode)

```
cli.ts (fetch-my-tasks-api)
  → b24FetchTasks() — REST API список задач (пагинация)
  → filters: stage ∈ openStageIds + responsible = userId
  → b24BatchTasksWithComments() — batch ceil(N/25) HTTP calls
    → per task: tasks.task.get + task.commentitem.getlist (в 1 batch)
    → fetchBodyImages() — параллельные HEAD запросы для вложений (URL only, no download)
  → [withContext] b24BatchTasksWithComments(parentIds) — batch для parent stories
  → [withSiblings] b24BatchListByParent() + b24BatchTasksWithComments() — batch для sibling tasks
  → output to stdout (no fs writes)
```

### Key modules

| Файл | Назначение |
|---|---|
| `src/cli.ts` | CLI entry point: `fetch-my-tasks-api`, `webhook` |
| `src/config.ts` | `.env`, `env`, `initStages()`, live bindings `openStageIds`, `stageNameToIds`, `allStageNames` |
| `src/api/b24-client.ts` | Bitrix24 REST API: `b24Call`, `b24Batch`, `b24BatchTasksWithComments`, `b24BatchListByParent`, `buildDiskAttachUrl` |
| `src/api/task-fetcher-api.ts` | Высокоуровневая логика: `fetchFullTaskDetail`, `fetchMyTasksViaApi`, `fetchSiblingTasks` |
| `src/mcp-server.ts` | MCP server (stdio): инструменты get_my_tasks, get_task, fetch_sphere_static, comments, time. `assertWriteEnabled()` guards all write ops |
| `src/mcp/formatters.ts` | Форматирование TaskWithContext в markdown. Картинки — ссылки на Bitrix URL |
| `src/mcp/utils.ts` | MCP helpers: ok/err, isApiConfigured |
| `src/commands/fetch-my-tasks-api.ts` | CLI команда для API mode |
| `src/webhook-server.ts` | HTTP webhook server (B24 outgoing webhooks) |
| `src/filters.ts` | `isDevWorkType` — классификация FE/BE/QA задач |
| `src/types.ts` | `Task`, `TaskDetail`, `TaskWithContext`, `Comment`, `BodyImage` |
| `src/utils/format.ts` | `stripBBCode`, `formatSeconds` |
| `src/utils/logger.ts` | Цветной консольный логгер. Custom stderrReporter — stdout чист для JSON-RPC |

### Legacy (src/legacy/)

Browser mode — не используется в production, требует VPN:

- `src/legacy/commands/` — batch-detail, detail-ctx, detail, dump, fetch-my-tasks, parse
- `src/legacy/scraper/` — browser, detail, kanban, static-fetcher
- `src/legacy/storage.ts` — unstorage cache (убран из основного flow)

### Data flow

```
B24TaskRaw (API response)
  → Task (list item)
    → TaskDetail (full: fields, comments, bodyImages with URL-only refs)
      → TaskWithContext (task + parentStory + relatedBackendTasks)
        → formatted markdown → agent (no fs writes)
```

### Business logic (filters.ts)

- **Стадии "Открыто"/"В работе"** — `openStageIds` из `initStages()`. Определяются динамически по `SYSTEM_TYPE ∈ {NEW, WORK}` + title-паттернам (`B24_OPEN_STAGE_TITLES`). Fallback — `B24_OPEN_STAGE_IDS`.
- **FE-задача** — `workType` содержит "фронтенд" или title начинается с `[FE]`
- **BE-задача** — `workType` содержит "бэкенд" или title начинается с `[BE]`
- **Sibling BE tasks** — задачи с тем же parent, у которых title начинается с `[BE]`
- **Parent Story** — загружается по `parentTaskId` для понимания общего контекста задачи

## Key Patterns

- **ES modules** (`"type": "module"` в package.json) — `.js` расширения в imports
- **Bitrix24 Batch API** — `POST /batch.json`, до 50 команд в 1 HTTP запрос. `b24BatchTasksWithComments` — 25 задач × 2 команды = 50. `b24BatchListByParent` — до 50 `tasks.task.list` за 1 вызов
- **No auto-downloads** — вложения НЕ скачиваются автоматически. Только URL-ссылки в ответе
- **MCP server** — stdio transport, read-only default. Инструменты: `get_my_tasks`, `get_task` (with `with_context`), `get_tasks_batch`, `fetch_sphere_static`, `add_comment`, `edit_comment`, `delete_comment`, `log_time`, `get_time`, `delete_time`
- **`get_tasks_batch`** — N задач за 1 pipeline вместо N вызовов `get_task`. `tasks` принимает либо ID-строки, либо `{ task_id, with_context }`; top-level опции = дефолт на все задачи, per-task значение перебивает. Под капотом `fetchTasksBatch` (`src/api/task-fetcher-api.ts`) — дедуп родителей и сиблингов, теги одним `b24BatchFetchTags`. `get_task` идёт через тот же `fetchTasksBatch`
- **Dynamic stages** — `initStages()` вызывается при старте, заполняет `openStageIds` и `stageNameToIds` через `task.stages.get` по группам из `B24_GROUP_IDS`
- **VPN обязателен** всегда (Cisco VPN с 2FA)

## Bitrix24 API notes

- **REST API**: webhook URL формат `https://sphere.loodsen.ru/rest/<USER_ID>/<TOKEN>/`
- **Batch**: `cmd[key]=method?param1=val1&param2=val2`, ответ `result.result.key`
- **Вложения**: URL через `buildDiskAttachUrl(attachedId, action)` с embedded auth
- **Tags** — доступны через `task.item.getdata` (old-style API). `tasks.task.list` с `select=["*"]` не возвращает теги. В pipeline: отдельный batch после получения деталей задачи
- **Комментарии**: `task.commentitem.getlist` — old-style метод, только `TASKID` + `ORDER`
- **Входящий вебхук**: Приложения > Разработчикам > Другое > Входящий вебхук. Выбрать права: Задачи (task), Диск (disk)
- **Исходящий вебхук**: Приложения > Разработчикам > Другое > Исходящий вебхук. Выбрать событие, указать URL

## Environment

Required:
- `B24_WEBHOOK_URL` — webhook URL из Bitrix24

Optional: `B24_USER_ID` (авто из URL), `B24_GROUP_IDS` (ID досок через запятую), `B24_OPEN_STAGE_TITLES` (default `В работе`), `SPHERE_BASE_URL` (default `https://sphere.loodsen.ru`), `MCP_WRITE_ENABLED` (default `false`)

Browser mode only: `SPHERE_EMAIL`, `SPHERE_PASSWORD`

VPN: Cisco VPN с 2FA — требуется всегда.

## Docker

```bash
npm run docker:build   # Build image
npm run docker:up      # docker compose up sphere-api
```
