# Подключение коннектора в claude.ai

Нужен готовый сервер (`ROOT-STEPS.md` выполнен) и ключ коннектора из шага 4 оттуда. Адрес сервера:
`https://multica.yakutov.com/mcp`.

## Добавить

1. claude.ai → **Customize → Connectors** → **+ Add** → **Add custom connector**.
2. Имя: `Multica`. URL: `https://multica.yakutov.com/mcp`. **Continue**.
3. **Authentication**: **No sign in** (вход идёт ключом в заголовке, не OAuth).
4. **Request headers**: имя `Authorization`, значение `Bearer <ключ коннектора>`.
5. **Add**. В чате: «+» внизу слева → **Connectors** → включить `Multica`.
6. Проверка: «Покажи зависшие задачи в stt за последний час» → вызов `list_issues(stale_minutes=60)`.

Коннектор, добавленный на компьютере, работает и в приложении на телефоне: запросы идут из облака Anthropic, а не с
устройства. Мак при этом может спать. Названия пунктов меню Anthropic иногда меняет; актуальный порядок:
https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

Claude Code с ноутбука ходит напрямую, а не из облака Anthropic: его адрес нужно добавить в `MULTICA_MCP_EXTRA_IPS`
(ROOT-STEPS.md, шаг «Caddy»).

## Как пользоваться

- «Что висит?» — `list_issues` с `stale_minutes`.
- Вернул задачу в `todo` — статус сам агента не будит. Скажи: «разбуди TST-123» (`wake_issue`). Если у исполнителя уже
  есть ран, повторного не будет: ответ `already_active`.
- Комментарий по умолчанию идёт как `/note …`: виден в задаче, но агента не будит. Чтобы разбудить, скажи «разбуди».
- Все записи видны в Multica от имени «Claude (MCP)»; журнал — `/var/lib/multica-tasks-mcp/audit.jsonl`.

## Ротация и отзыв

- **Ключ коннектора** (раз в квартал или при подозрении на утечку): на сервере сгенерировать новый
  (`openssl rand -hex 32`), заменить `MULTICA_MCP_KEY` в `/etc/multica-tasks-mcp/env`,
  `sudo systemctl restart multica-tasks-mcp`, в claude.ai обновить заголовок. Старый ключ перестаёт работать сразу.
- **PAT** сервисного пользователя живёт 90 дней. За неделю до конца выпустить новый (Settings → Tokens под пользователем
  «Claude (MCP)»), заменить `MULTICA_PAT`, перезапустить сервис, отозвать старый. Хорошо поставить себе задачу с
  будильником на напоминание.
- **Срочно отключить**: `sudo systemctl stop multica-tasks-mcp` и отозвать PAT в Multica. Это не затрагивает остальное.
