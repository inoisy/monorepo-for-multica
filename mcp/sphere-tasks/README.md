# sphere-tasks

**MCP-сервер + CLI** для работы с задачами Bitrix24 (Sphere) на `https://sphere.loodsen.ru`.

API-only: никаких браузеров, Playwright. Только Bitrix24 REST API. Требуется VPN (Cisco, 2FA).

## Установка

```bash
npm install
```

Конфигурация передаётся через env в конфиге агента — файл `.env` нужен только для локальной разработки.

## Настройка

### 1. Входящий вебхук в Bitrix24

**Приложения → Разработчикам → Другое → Входящий вебхук**

1. Задайте название (например, `mcp-sphere`)
2. Выберите права: `Задачи (task)`, `Диск (disk)`
3. Сохраните — получите URL вида:
   ```
   https://sphere.loodsen.ru/rest/<USER_ID>/<TOKEN>/
   ```
4. Скопируйте его в `.env` как `B24_WEBHOOK_URL`

### 2. Исходящий вебхук (опционально)

Для отправки событий из Bitrix24 наружу:

**Приложения → Разработчикам → Другое → Исходящий вебхук**

1. Заполните название
2. Выберите событие (например, «Обновление задачи»)
3. Укажите URL вашего сервиса
4. Выберите права: `Задачи (task)`, `Диск (disk)`
5. Сохраните

## Переменные окружения

| Переменная | Обязательно | Описание |
|---|---|---|
| `B24_WEBHOOK_URL` | Да | Webhook URL из Bitrix24 |
| `B24_USER_ID` | Нет | ID пользователя (авто из URL, override только если нужно) |
| `B24_GROUP_IDS` | Нет | Comma-separated ID групп (для динамической загрузки стадий) |
| `B24_OPEN_STAGE_TITLES` | Нет | Title-паттерны открытых стадий (default: `В работе`) |
| `MCP_WRITE_ENABLED` | Нет | `false` (default) — блокирует write-операции |

## Быстрый старт

### CLI

```bash
# Извлечь мои задачи (API mode)
tsx src/cli.ts fetch-my-tasks-api

# Webhook сервер (port 3100) для B24 outgoing webhooks
tsx src/cli.ts webhook

# Проверить конфигурацию
tsx src/cli.ts fetch-my-tasks-api --all-stages
```

### MCP Inspector

```bash
npm run mcp:inspect
# → http://localhost:6270
```

## MCP инструменты

| Инструмент | Описание |
|---|---|
| `get_my_tasks` | Мои задачи (живые из API). Параметры: `include_comments`, `all_stages`, `stage_names` |
| `get_task` | Одна задача. Параметры: `task_id`, `with_context` |
| `fetch_sphere_static` | URL-ссылка на файл (image, PDF, DOCX, XLSX) |
| `add_comment` / `edit_comment` / `delete_comment` | Комментарии (нужен `MCP_WRITE_ENABLED=true`) |
| `log_time` / `get_time` / `delete_time` | Трекинг времени |

## Архитектура

```
MCP (stdio) ←→ mcp-server.ts
                   ↓
              task-fetcher-api.ts
                   ↓
              b24-client.ts (batch API)
                   ↓
              Bitrix24 REST API

CLI → commands/ → task-fetcher-api → b24-client → Bitrix24
```

**Batch API:** 25 задач × 2 команды = 1 HTTP запрос. `ceil(N/25)` вместо N×2.

## Развертывание

MCP-сервер — процесс без портов. Агент (Hermes / OpenCode / Claude Code / Pi) запускает его как subprocess и общается через JSON-RPC stdin/stdout.

### На сервере

```bash
# 1. Клонировать и установить
git clone https://git01.loodsen.ru/loodsen/ai/mcp-sphere.git /opt/mcp-sphere
cd /opt/mcp-sphere
npm install

# 2. Подключить к агенту — каждый пользователь добавляет в свой ~/.hermes/config.yaml:
```

```yaml
mcp_servers:
  sphere:
    command: tsx
    args: [/opt/mcp-sphere/src/mcp-server.ts]
    env:
      B24_WEBHOOK_URL: https://sphere.loodsen.ru/rest/<USER_ID>/<TOKEN>/
      B24_GROUP_IDS: "65,50,224"   # ID досок пользователя (через запятую)
      # B24_USER_ID: "425"         # опционально: авто из URL, override если нужно
```

`B24_USER_ID` не нужен — извлекается автоматически из `B24_WEBHOOK_URL`.

Агент поднимает процесс автоматически. Перезапустите агента после изменения конфига.

### Docker (опционально)

```bash
npm run docker:build
npm run docker:up
```

При использовании с Docker, измените command:
```yaml
mcp_servers:
  sphere:
    command: node
    args: [dist/mcp-server.js]
    env:
      B24_WEBHOOK_URL: https://sphere.loodsen.ru/rest/<USER_ID>/<TOKEN>/
      B24_GROUP_IDS: "65,50,224"
```

## Разработка

```bash
npm run check      # typecheck + lint
npm run build      # compile → dist/
npm run mcp:inspect  # MCP Inspector для тестирования
```