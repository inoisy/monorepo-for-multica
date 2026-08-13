# CONTEXT.md

Проект: sphere-tasks
Дата: 2026-05-15

## Назначение

**MCP-сервер + CLI утилита** для работы с задачами Bitrix24 (Sphere, `https://sphere.loodsen.ru`).

**Единственный режим:** API mode — Bitrix24 REST API через webhook. Никаких браузеров, batch-запросы.

**Кому:** разработчикам, которым нужно видеть свои задачи с полным контекстом (описание, комментарии, parent Story, связанные BE-задачи, вложения).

## Структура задач в Sphere

```
Epic (Эпик)
  └── Feature (Фича)
        └── Story (Стори) — общее описание фичи
              ├── [BE] Бэкенд-задача — реализация API/backend
              ├── [FE] Фронтенд-задача
              ├── [QA] QA-задача
              └── [BA] Аналитика
```

## Критерии фильтрации

1. **Стадия:** открытые стадии из `openStageIds` (загружаются динамически через `initStages()` при старте). Можно переопределить через `--all-stages` или `--stage <ids>`
2. **Responsible:** текущий пользователь по `B24_USER_ID`

## Что собирается для каждой задачи

| Что | Зачем |
|---|---|
| Описание (body) | Что нужно сделать |
| Комментарии | Обсуждения, актуальная информация |
| Вложения (bodyImages) | URL-ссылки на файлы (DOCX/XLSX/PDF/картинки) |
| Parent Story | Общий контекст фичи |
| Sibling [BE] задачи | Готов ли бэкенд |
| Sidebar fields | Стадия, приоритет, дедлайн, затраченное время |

## Формат вывода

MCP отдаёт markdown (no fs writes):

```
# [157529] Задача
Stage: В работе | Priority: Высокий

## Description
<body>

## Parent Story [102853]
<story body + comments>

## Backend Tasks
### [157531] [BE] ...
<BE body>

## Comments (3)
<comments>
```

## Статус проекта (v2.0)

- **MCP server** — 9 инструментов: `get_my_tasks`, `get_task`, `fetch_sphere_static`, `add_comment`, `edit_comment`, `delete_comment`, `log_time`, `get_time`, `delete_time`
- **CLI команды** — fetch-my-tasks-api, webhook
- **Dynamic stages** — `initStages()` загружает стадии из Bitrix24 API при старте
- **Batch API** — ceil(N/25) запросов вместо N×2

## Технический стек

- TypeScript 5.3, Node.js 24 (ESM)
- `@modelcontextprotocol/sdk` — MCP сервер (stdio)
- `tsx` — запуск без сборки
- `vitest` — тесты

## Конфигурация

```env
# Обязательно
B24_WEBHOOK_URL=https://sphere.loodsen.ru/rest/<USER_ID>/<TOKEN>/

# Общие
SPHERE_BASE_URL=https://sphere.loodsen.ru
B24_USER_ID=           # numeric user ID

# Стадии (динамически из API)
B24_GROUP_IDS=         # comma-separated group IDs для загрузки стадий
B24_OPEN_STAGE_TITLES= # title-паттерны открытых стадий (default: В работе)
B24_OPEN_STAGE_IDS=    # fallback: comma-separated stage IDs

# Типы работ
B24_WORKTYPE_FE_ID=
B24_WORKTYPE_BE_ID=
B24_WORKTYPE_QA_ID=

# Write-операции
MCP_WRITE_ENABLED=false
```

## Тестирование MCP

```bash
# Inspector UI (port 6270)
npm run mcp:inspect
```
