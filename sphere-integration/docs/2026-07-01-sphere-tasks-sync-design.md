# sphere-tasks sync — Design Doc

**Дата:** 2026-07-01  
**Статус:** Approved

---

## Цель

Автоматическая синхронизация задач из Bitrix/Sphere в отдельный git-репо (`sphere-tasks`), который используется AI-агентами как источник контекста и монтируется как Obsidian vault.

---

## Два репо

### `sphere-tasks` (данные — для агентов и Obsidian)

```
sphere-tasks/
  tasks/
    {id}-{slug}/
      index.md          # YAML frontmatter + описание + кастомные поля
      comments.md       # все комментарии хронологически
      checklist.md      # чеклисты
      subtasks/
        {id}.md
  epics/
    {id}-{slug}/
      index.md
  _meta/
    last-sync.json      # timestamp последнего синка + список изменений
    SYNC-LOG.md         # история синков
  README.md             # инструкция для агентов (структура репо)
```

Формат `index.md` каждой задачи:

```markdown
---
id: 160466
title: "Тогл каталога"
status: "В работе"
assignee: "Евгений Якутов"
epic: 159455
deadline: 2026-07-15
created: 2026-06-01
updated: 2026-07-01
stage: 3397
tags: [frontend, online-sale]
---

## Описание
...

## Кастомные поля
...

## Вложения
- [filename](url)
```

### `sphere-sync` (сервис — DevOps)

```
sphere-sync/
  src/
    server.ts           # Express :3000/webhook — приём вебхуков Bitrix
    sync.ts             # ядро: fetch → markdown → git push
    bitrix.ts           # Bitrix REST API клиент
    formatters/
      task.ts           # задача → index.md
      comment.ts        # комментарии → comments.md
      checklist.ts      # чеклисты → checklist.md
  scripts/
    sync-all.sh         # полный синк всех задач
    sync-task.sh        # синк одной задачи по ID
  .github/
    workflows/
      scheduled.yml     # cron каждый час
      dispatch.yml      # ручной запуск / repository_dispatch
  Dockerfile
  docker-compose.yml
  .env.example
```

---

## Data Flow

```
Bitrix (любое изменение задачи)
  │
  │ исходящий вебхук
  ▼
VPS / Docker — sphere-sync
  Express :3000/webhook
  → валидация secret token
  → sync-task.sh <id>          (немедленно, ~1 сек)
  → POST GitHub API dispatch   (параллельно, ~30 сек)
  │
  ├── sync-task.sh
  │     └── Bitrix REST API → markdown → git commit + push
  │
  └── GitHub Actions
        ├── dispatch (триггер от VPS)
        └── scheduled (cron каждый час — fallback)
              └── sync-all.sh → git commit + push
                    ↓
              sphere-tasks repo
                    │
           ┌────────┴────────┐
           ▼                 ▼
      Obsidian           AI агенты
      Git plugin         MCP / clone
      auto-pull
```

---

## Три режима синка

| Режим | Триггер | Задержка |
|---|---|---|
| VPS realtime | Bitrix вебхук | ~1 сек |
| GitHub Actions dispatch | VPS → GitHub API | ~30 сек |
| GitHub Actions scheduled | cron каждый час | до 60 мин |
| Локальный Mac cron | launchd раз в час | до 60 мин |
| Ручной | `sphere refresh [id]` | мгновенно |

Режимы независимы — если VPS упал, scheduled Actions подхватит через ≤60 мин.

---

## Obsidian

Клонировать `sphere-tasks` как vault или подпапку:

```bash
git clone git@github.com:org/sphere-tasks.git ~/obsidian/sphere-tasks
```

Плагины:
- **Obsidian Git** — auto-pull при открытии, каждые N минут
- **Dataview** — живые таблицы по frontmatter

Пример Dataview запроса:

```dataview
TABLE status, assignee, deadline
FROM "tasks"
WHERE epic = 159455
SORT status ASC
```

---

## AI агенты

**Рекомендуемый способ — MCP filesystem resource:**  
`sphere-tasks` монтируется как MCP resource. Агент читает нужные файлы по запросу.

**Альтернатива — git clone в scratchpad:**  
Агент клонирует репо, читает `README.md` + нужные `index.md`.

`README.md` в корне `sphere-tasks` содержит схему репо и примеры grep-поиска для агентов.

---

## Безопасность

Bitrix webhook токен валидируется на VPS:

```typescript
const token = req.headers['x-bitrix-token'];
if (token !== process.env.WEBHOOK_SECRET) return res.status(401).end();
```

Переменные окружения (не в git):
```env
WEBHOOK_SECRET=...
BITRIX_WEBHOOK_URL=https://your-bitrix.bitrix24.ru/rest/1/...
GITHUB_TOKEN=...
TASKS_REPO=org/sphere-tasks
```

---

## Обработка ошибок

| Сценарий | Поведение |
|---|---|
| Bitrix API недоступен | retry 3 раза с exponential backoff, запись в SYNC-LOG.md |
| git push конфликт | `git pull --rebase` перед push |
| Вебхук пришёл дважды | идемпотентно — файл перезаписывается, коммит только если diff |
| VPS упал | GitHub Actions scheduled подхватит через ≤60 мин |
| GitHub Actions упал | VPS realtime продолжает работать |

---

## Формат коммитов в `sphere-tasks`

```
sync: task #160466 status → Готово [2026-07-01T14:32:00Z]
sync: task #161664 comment added [2026-07-01T14:35:00Z]
sync: full sweep — 3 tasks updated [2026-07-01T15:00:00Z]
```

---

## Что НЕ входит в scope

- UI/dashboard для просмотра задач (Obsidian закрывает это)
- Двусторонняя синхронизация (Git → Bitrix)
- Хранение бинарных вложений (только ссылки)
