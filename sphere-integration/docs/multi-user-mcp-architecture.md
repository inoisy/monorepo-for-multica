# MCP Sphere: мульти-пользовательский доступ

**Контекст:** Раскатываем агентов (Hermes + Multica) на всю компанию. MCP-сервер sphere-integration сейчас работает с одним пользователем (webhook hardcoded в env). Нужна архитектура для 50–500 сотрудников.

**Авторизация в Multica:** через корпоративный Keycloak (SSO).  
**Keycloak + B24 уже интегрированы:** пользователи логинятся в B24 через Keycloak. Это означает:
- Email гарантированно совпадает в обеих системах (один IdP)
- B24 userId, вероятно, уже доступен как Keycloak JWT claim или user attribute
- Проблема маппинга identity **решена на инфраструктурном уровне**

**Scope этого документа:** только **read** (get_my_tasks, get_task). Write-атрибуция — отдельная тема.

---

## Проблема

Текущий код привязан к одному пользователю в двух местах:

```
task-fetcher-api.ts:190  →  const userId = env.userId  (из webhook URL)
b24-client.ts:68         →  const webhookUrl = env.webhookUrl  (один на весь процесс)
```

`get_my_tasks` всегда возвращает задачи владельца webhook, независимо от того, кто запрашивает.

---

## Вариант 1: Один admin webhook + userId как параметр

### Принцип

`tasks.task.list` поддерживает `FILTER[RESPONSIBLE_ID]` для любого пользователя.  
Admin webhook с правами на задачи видит всех. Multica инжектирует `user_id` из сессии в каждый tool call.

### Схема

```
Сотрудник (vasya@company.ru)
    ↓
Multica — знает сессию → email → B24 userId: 42
    ↓ inject { user_id: "42" }
Hermes → get_my_tasks({ user_id: "42" })
    ↓
Sphere MCP (1 процесс, 1 admin webhook)
    ↓ tasks.task.list?FILTER[RESPONSIBLE_ID]=42
Bitrix24 API (self-hosted, VPN)
    ↓ задачи пользователя 42
```

### Маппинг email → B24 userId: уже решено

Т.к. B24 интегрирован с Keycloak, при логине пользователя в B24 Keycloak уже хранит связь аккаунтов.

**Проверить в первую очередь:** есть ли `b24_user_id` (или аналог) в JWT claims.

```bash
# Декодировать JWT из Multica-сессии:
echo "<jwt_payload>" | base64 -d | jq .
# Ищем: b24_user_id, bitrix_id, или любой числовой claim
```

Если claim есть → Multica читает напрямую, нулевой overhead.

Если нет → добавить mapper в Keycloak Client:
```
Keycloak → Clients → multica → Client scopes → Add mapper
Type: User Attribute
User Attribute: b24_user_id
Token Claim Name: b24_user_id
```

Атрибут `b24_user_id` уже должен быть в Keycloak если B24-интеграция настроена правильно — B24 при первом SSO-логине обычно сохраняет свой userId в IdP.

**Итог:** никакого `user.search` API, никакой отдельной БД. Identity flow:
```
Сотрудник логинится в Multica через Keycloak SSO
→ JWT: { email: "vasya@...", b24_user_id: "42", ... }
→ Multica инжектирует user_id: "42" в каждый MCP tool call
```

### Изменения в sphere-integration

**3 файла, ~20 строк:**

1. `src/api/task-fetcher-api.ts` — добавить `userId?: string` в опции `fetchMyTasksViaApi`, использовать вместо `env.userId`
2. `src/mcp-server.ts` — добавить `user_id` в inputSchema `get_my_tasks`, пробросить в `fetchMyTasksViaApi`
3. `src/api/task-fetcher-api.ts:49` — `detailUrl` использует `raw.responsible.id` вместо `env.userId`

### Изменения в Multica

- При логине через Keycloak: извлечь `b24_user_id` из JWT claim (если атрибут настроен) или сделать `user.search` по email один раз
- При каждом tool call: инжектировать `user_id` из сессионного контекста

### Плюсы
- Нулевой онбординг для сотрудников
- Один MCP-процесс на всю компанию
- Минимальные изменения в коде
- Работает сегодня

### Ограничения
- Write ops (комментарии, время) — от имени admin webhook, не сотрудника
- Единая точка отказа: admin webhook отозван → всё падает
- Нужен B24 userId для каждого сотрудника (решается через `user.search` автоматически)

---

## Вариант 2: Per-user webhooks + spawn per session

### Принцип

Каждый сотрудник один раз создаёт свой B24 webhook. Multica хранит `{ email → webhookUrl }`. При старте сессии — spawn отдельного MCP-процесса с webhook этого пользователя в env.

### Схема

```
Multica: { vasya@company.ru → "https://sphere.loodsen.ru/rest/42/abc.../", ... }
    ↓ при старте сессии
spawn node dist/mcp-server.js
     env: B24_WEBHOOK_URL=https://sphere.loodsen.ru/rest/42/abc.../
    ↓
5 активных сессий = 5 MCP-процессов (~30 MB каждый)
```

### Онбординг (1 раз на сотрудника)

```
B24 → Приложения → Разработчикам → Входящий вебхук
→ Права: Задачи (task), Диск (disk)
→ Скопировать URL: https://sphere.loodsen.ru/rest/42/abc.../
→ Вставить в настройки Multica → автоматическая валидация через user.current
```

### Изменения в sphere-integration

Никаких. Текущий код работает as-is.

### Изменения в Multica

- UI: поле "Bitrix24 webhook URL" в настройках профиля пользователя
- Валидация URL при сохранении: вызов `user.current` через webhook
- Spawn MCP с `B24_WEBHOOK_URL=user_webhook` при старте сессии агента
- Kill процесса при завершении сессии
- **С Keycloak:** webhook URL можно хранить как Keycloak user attribute (`b24_webhook_url`) — тогда не нужна отдельная БД в Multica, всё в IdP

### Плюсы
- Write ops атрибутируются правильному пользователю
- Нет изменений в MCP-сервере
- Полная изоляция по пользователям

### Ограничения
- 500 ручных онбордингов — поддержка превращается в боль
- Пользователь пересоздал webhook → нужен повторный онбординг
- Webhook URL содержит токен — риск утечки при копипасте в Slack/почту
- Process management: нужен lifecycle в Multica (spawn/kill/health check)

---

## Вариант 3: B24 OAuth Application

### Принцип

Регистрируется одно OAuth-приложение в self-hosted B24. Сотрудник кликает "Подключить Bitrix24" → OAuth redirect → Multica получает `access_token` + `refresh_token`. Все API-вызовы идут с токеном конкретного пользователя.

### Плюсы
- Правильная атрибуция read и write
- Zero-onboarding: один клик
- Централизованное управление доступом из B24

### Ограничения
- Требует реализации OAuth flow в Multica (не тривиально)
- B24 `access_token` живёт 1 час → нужен refresh daemon
- Сложность внедрения на порядок выше, чем варианты 1 и 2
- Требует создания B24-приложения с настройкой redirect URI

---

## Сравнение

| Критерий | Вариант 1 | Вариант 2 | Вариант 3 |
|---|:---:|:---:|:---:|
| Онбординг пользователя | Авто | Ручной (webhook) | Один клик |
| Read-задачи правильного юзера | ✅ | ✅ | ✅ |
| Write от имени юзера | ❌ (admin) | ✅ | ✅ |
| Изменения в MCP | ~20 строк | Нет | Существенные |
| Изменения в Multica | Маппинг email→ID | Хранение + spawn | OAuth flow |
| Масштаб (500+ чел) | ✅ 1 процесс | ⚠️ N процессов | ✅ 1 процесс |
| Операционная надёжность | ✅ | ⚠️ | ✅ |
| Время на реализацию | 2–3 дня | 3–5 дней | 2–3 недели |

---

## Рекомендованный roadmap

### Фаза 1 — сейчас (MVP read, Вариант 1)

- **Keycloak:** проверить наличие `b24_user_id` в JWT; если нет — добавить mapper в Keycloak Client
- **sphere-integration:** `userId` как параметр tool call (~20 строк)
- **Multica:** при логине читать `b24_user_id` из JWT claim → инжектировать в tool calls
- **Деплой:** один MCP-процесс, один admin webhook (служебный B24-аккаунт)
- **Результат:** все сотрудники читают свои задачи через единый SSO, ноль онбординга

### Фаза 2 — правильный write

Т.к. B24 уже интегрирован с Keycloak через SSO — пользователь уже "доказал" свою identity Keycloak. Логичный путь:

**B24 REST API с токеном пользователя через Keycloak:**  
Если интеграция B24+Keycloak реализована через OAuth/OIDC (самый распространённый способ), B24 принимает Keycloak access_token для API-запросов. Нужно уточнить у команды, которая настраивала интеграцию:
- Какой тип интеграции: SAML или OIDC?
- Если OIDC — B24 REST API принимает Bearer token от Keycloak?

Если да — write ops отправляются с Keycloak токеном пользователя прямо в B24 API. Никаких дополнительных webhook, никакого OAuth flow внутри Multica.

### Фаза 3 — advanced

- **RBAC через Keycloak roles:** роль `b24-agent-write` → Multica разрешает write ops
- Audit log всех tool calls (кто, когда, какой tool, какой task)
- Rate limiting per user (B24 лимиты: 2 req/s per webhook, 50 cmd/batch)
- B24 outgoing webhooks → push-уведомления в Multica при изменении задач

---

## Вопросы для обсуждения

1. **Какой claim в JWT содержит B24 userId?** Декодировать Keycloak-токен текущей сессии — там должен быть атрибут. Это разблокирует Фазу 1.
2. **Какой тип интеграции B24+Keycloak: SAML или OIDC?** От этого зависит, можно ли передавать Keycloak-токен в B24 REST API для write ops.
3. **Есть ли служебный B24-аккаунт с доступом ко всем группам?** Нужен для admin webhook — читает задачи всех, но не пишет.
4. **Write атрибуция критична в первой волне?** Если агенты только читают — Фаза 1 закрывает всё. Write можно добавить после.
5. **Сколько сотрудников в первой волне?** Влияет на выбор варианта только если write важен сейчас.
