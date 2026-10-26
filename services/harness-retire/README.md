# STT-454: переключение и снятие старой выкатки

Это инструкция для ворот **merge**, не разрешение выполнить root-шаги в dev.
PR не сливать до QA/review. Задачи Сферы нет, используется T-12345.
Удаление canary и связанных юнитов принадлежит STT-454, не STT-429.

## Обязательный незакрытый блокер

На 26.10.2026 `deploy/autodeploy/autodeploy.py` из `inoisy/multica` жёстко
перечисляет backend/frontend в `render_override`, `current_images`, `pull`,
`up --no-deps`, автоматическом и ручном откате. `wait_health` проверяет только
`/health` платформы. Compose-файл сам по себе не подключает MCP к этим операциям.

Запрет менять этот код сверх compose в текущей постановке несовместим с общим
откатом MCP. Пока автор не уточнил границу и интеграция не реализована и не
проверена, **здесь остановиться: службы не переключать и пакет не удалять**.
Нужны как минимум включение MCP в списки образов/сервисов, проверка его health
и выпуск его образа на ту же ревизию релиза платформы. Код MCP живёт в другом
репозитории; связь версий должна быть закреплена явно, а не через плавающий main.

Ниже — подготовленные команды последующего переключения. Они исполнимы только
после устранения блокера и получения одобренного образа. Ручная установка
контейнера ещё не доказывает участие в multica-autodeploy.

## 1. Снимок и проверка замены

Оператор root задаёт `$REPO` — root-доверенную копию monorepo-for-multica на
одобренном SHA. Ветка и SHA всех сопутствующих PR записываются в отчёт merge.
Не использовать изменяемую агентами рабочую копию как root-скрипт.

До снимка проверить отсутствие операции старого механизма:
`systemctl list-units 'harness-op-*' --state=running,activating` и
`harness-control ops`. При наличии операции дождаться её завершения.

```sh
SNAP=/var/backups/stt-454-$(date -u +%Y%m%dT%H%M%SZ)
install -d -o root -g root -m 0700 "$SNAP"
printf '%s\n' "$SNAP" > /var/backups/stt-454-last
# Снимок существующих файлов, включая правила доступа; секреты не печатаются.
tar -C / -czpf "$SNAP/legacy.tgz" \
  etc/harness-control etc/sudoers.d/harness-control \
  usr/local/lib/harness-control usr/local/lib/harness-canary \
  usr/local/bin/harness-control usr/local/bin/harness-control-mcp usr/local/sbin/harness-priv \
  etc/systemd/system/harness-control-recover.service \
  etc/systemd/system/harness-canary.service etc/systemd/system/harness-canary.timer \
  etc/systemd/system/multica-tasks-mcp.service
cp -a /var/lib/harness-control "$SNAP/state"
cp -a /var/lib/multica-tasks-mcp "$SNAP/audit"
cp -a /opt/multica/docker-compose*.yml "$SNAP/"
systemctl is-enabled multica-tasks-mcp.service harness-control-recover.service harness-canary.timer > "$SNAP/enabled.txt" || true
systemctl is-active multica-tasks-mcp.service harness-control-recover.service harness-canary.timer > "$SNAP/active.txt" || true
```

Отчёты/архивы root 0700, пароли в задачу не переносить.

Сначала поставить и проверить bio-замену по `../bio-media-deploy/README.md`.
Доверенный broker-guard перенести до удаления пакета. Прежний брокер не менять
прямым копированием из рабочей копии: установка — через одобренный снимок и юнит.

## 2. MCP: проверка на другом порту, затем переключение

Секреты остаются в `/etc/multica-tasks-mcp/env` (root 0600), аудит — в
`/var/lib/multica-tasks-mcp`. Host networking сохраняет loopback: текущие Caddy,
доверие к X-Forwarded-For и API URL `127.0.0.1:8080` работают без смены периметра.
Сервис в контейнере работает с UID/GID существующего пользователя, без capabilities.

```sh
# MCP_IMAGE — одобренный неизменяемый образ image@sha256:..., выпущенный CI.
export MULTICA_TASKS_MCP_IMAGE="$MCP_IMAGE"
export MULTICA_MCP_UID=$(id -u multica-mcp)
export MULTICA_MCP_GID=$(id -g multica-mcp)
BASE=/opt/multica
ADDON="$REPO/mcp/multica-tasks/deploy/compose.production.yaml"
# Список -f сверить с com.docker.compose.project.config_files действующего
# backend; ниже показан набор файлов этой установки на 26.10.
compose_mcp() {
  docker compose -p "${COMPOSE_PROJECT:?project from backend labels}" --project-directory "$BASE" \
    -f "$BASE/docker-compose.selfhost.yml" \
    -f "$BASE/docker-compose.v070.override.yml" \
    -f "$BASE/docker-compose.autodeploy.yml" -f "$ADDON" "$@"
}
compose_mcp config --quiet
# Пробный экземпляр не использует общий аудит и не занимает порт работающего MCP.
compose_mcp run -d --no-deps --name stt-454-mcp-probe \
  -e MULTICA_MCP_PORT=18101 -e STATE_DIRECTORY=/tmp/mcp-probe multica-tasks-mcp
# Проверка внутри контейнера; ключ читается из окружения и не выводится.
docker exec stt-454-mcp-probe python3 -I /app/deploy/probe.py --smoke
docker stop stt-454-mcp-probe
docker rm stt-454-mcp-probe
```

Ожидается `healthz=200; unauthenticated=401; tools=9; bad-origin=403`.
Контейнер ещё не заменяет действующую службу. Перед переключением сохранить
аддон root-файлом в `/opt/multica`, а не ссылкой в рабочую копию. Механизм
закрепления образа/UID/GID и подключения аддона к последующим автопроливкам
должен быть реализован в сопутствующем PR интеграции (блокер выше).

После его реализации, только на воротах merge:

```sh
systemctl stop multica-tasks-mcp.service
# При ошибке любой проверки ниже немедленно выполнить откат из раздела 4.
compose_mcp up -d --no-deps --wait --wait-timeout 60 multica-tasks-mcp
compose_mcp exec -T multica-tasks-mcp python3 -I /app/deploy/probe.py --smoke
# Этот тест не использует ключ и не обращается к Multica API.
curl --fail --silent http://127.0.0.1:8101/healthz
```

Пока не удалять юнит. Сохранить доказательства: релиз main меняет MCP-образ
вместе с backend/frontend, ошибка MCP-health возвращает **все три** прежних
образа, `multica-autodeploy rollback` также возвращает три образа; запись
`previous_images` содержит MCP. Приложить очищенный журнал
`journalctl -u multica-autodeploy` и `/var/log/multica-autodeploy.jsonl`.
Затем повторить smoke коннектора через Caddy из разрешённого адреса (401 без
ключа, MCP tools/list с ключом), без создания задач или ранов. Не отключать
ограничение IP ради проверки. Внешний `/mcp` с запрещённого адреса остаётся 403.

## 3. Снятие — только после всех проверок выше

Исполняется оператором на merge; старый пакет до этого сохранён. Не применять
его `uninstall.sh --restore-baseline`: он вернёт файлы заменяемых компонентов.

```sh
systemctl disable --now multica-tasks-mcp.service harness-control-recover.service \
  harness-canary.timer harness-canary.service
rm -f /etc/systemd/system/multica-tasks-mcp.service \
  /etc/systemd/system/harness-control-recover.service \
  /etc/systemd/system/harness-canary.service /etc/systemd/system/harness-canary.timer
rm -f /etc/sudoers.d/harness-control
rm -f /usr/local/bin/harness-control /usr/local/bin/harness-control-mcp /usr/local/sbin/harness-priv
rm -rf /usr/local/lib/harness-control /usr/local/lib/harness-canary /etc/harness-control
systemctl daemon-reload
systemctl reset-failed multica-tasks-mcp.service harness-control-recover.service harness-canary.timer harness-canary.service 2>/dev/null || true
# Оба вывода должны быть пустыми:
systemctl list-unit-files | grep -E 'harness|multica-tasks-mcp' || true
ls /usr/local/bin | grep harness || true
# Повторить проверки обеих замен:
compose_mcp exec -T multica-tasks-mcp python3 -I /app/deploy/probe.py --smoke
/usr/local/bin/bio-media-api --check
python3 -I /usr/local/lib/bio-media-deploy/broker_guard.py /usr/local/bin/bio-media-api
```

`/var/lib/harness-control` и старые файлы MCP оставить как архив на период
отката; службы их больше не используют. После слияния сопутствующего PR
stt-agents применить изменённый промпт Техдиректора штатным prompt-deploy.
Изменений промпта Девопса не требуется: в его исходнике нет обращений к
удаляемому инструменту. Удаление скилла из Multica и локальных кэшей — отдельные
операции merge, по CLI `multica skill delete --help`; перед удалением сохранить
его содержимое и список привязок. `prompt-deploy` сохраняется. Проверка в
stt-agents: `rg -l harness-control --glob '*.md' --glob '!docs/**'` — пусто;
`run-watch/prompt-map.json` не содержит удалённого скилла. Исторический аудит
в docs/research не переписывается.

## 4. Откат переключения

До удаления юнитов (обычный сценарий отказа):

```sh
compose_mcp stop multica-tasks-mcp
systemctl start multica-tasks-mcp.service
curl --fail --silent http://127.0.0.1:8101/healthz
```

После снятия пакета: сначала остановить compose MCP, затем вернуть архив,
не запуская два процесса на порту 8101:

```sh
compose_mcp stop multica-tasks-mcp
SNAP=$(cat /var/backups/stt-454-last)
tar -C / -xzpf "$SNAP/legacy.tgz"
systemctl daemon-reload
systemctl enable --now multica-tasks-mcp.service
curl --fail --silent http://127.0.0.1:8101/healthz
```

Восстанавливать enabled/active остальных юнитов по снимку, а не включать canary
вслепую (она была выключена). Актуальный аудит не заменять старой копией;
UID/GID не менялись. Если изменялась глобальная конфигурация автопроливки,
вернуть её сохранённую версию до нового запуска таймера. Откат bio — в
`../bio-media-deploy/README.md`. Откат промпта — `prompt-deploy rollback cto.md`,
скилл возвращается из сохранённой копии штатным CLI.
