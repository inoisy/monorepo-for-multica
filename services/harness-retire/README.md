# STT-454: переключение и снятие старой выкатки

Это инструкция для ворот **merge**, не разрешение выполнить root-шаги в dev.
PR не сливать до QA/review. Задачи Сферы нет, используется T-12345.
Удаление canary и связанных юнитов принадлежит STT-454, не STT-429.
Закреплённые сопутствующие ревизии для QA/review — в `revisions.json` рядом.
Это SHA подготовки; после merge оператор отдельно записывает SHA релизов main
и опубликованный image pin, а не подставляет их до выпуска образа.

## Интеграция MCP в multica-autodeploy

Автор 26.10 разрешил минимальное расширение `deploy/autodeploy/autodeploy.py`
(форк `inoisy/multica`, PR #83): MCP входит в списки сервисов/образов, health и
общий откат платформы. Нового механизма выкатки нет.

- Включается ключом `mcp_service` в `/etc/multica-autodeploy/config.json`
  (по умолчанию пусто — релизы идут как раньше). Настройку выполнять при
  остановленных timer/path, live-запуск — после остановки `multica-tasks-mcp.service`:
  оба слушают `127.0.0.1:8101`.
- Версия закреплена файлом `deploy/autodeploy/mcp-image` в том же коммите форка,
  что и релиз платформы: `ghcr.io/inoisy/multica-tasks-mcp:<40-hex sha>` или
  `@sha256:<digest>`, образ собирает CI этого репо на `main`. Плавающие теги
  отклоняются. Отсутствующий pin при включённом MCP также прерывает выкатку до
  изменений. После включения pin обязателен в каждом релизе.
- Выкатка: `pull`/`up --no-deps` backend, frontend и MCP; успех — `/health`
  платформы показывает SHA, контейнер MCP запущен на закреплённом образе,
  healthy и `http://127.0.0.1:8101/healthz` отвечает.
- Откат (автоматический при ошибке health и `multica-autodeploy rollback`) —
  все прежние образы из `previous_images`. Если MCP в прошлом релизе в compose
  не было, контейнер останавливается, а старый юнит запускает оператор.
- Compose-файл MCP — root-копия `/opt/multica/docker-compose.mcp.yml`; образ в нём
  задаёт override автовыкатки. Копия нужна root, а не ссылка на рабочую копию.

Эти шаги и всё ниже исполняются на воротах merge. До слияния PR #30 и #83 и
выпуска образа ничего на сервере не менять.

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
# Порядок: PR #83 слит и autodeploy переустановлен (deploy/autodeploy/install.sh
# из root-доверенной копии форка; config.json он не трогает), PR #30 слит, CI
# опубликовал образ. MCP_IMAGE — ghcr.io/inoisy/multica-tasks-mcp:<sha main>.
# Сохранить состояния триггеров и остановить их на время переключения.
systemctl is-active multica-autodeploy.timer multica-autodeploy.path > "$SNAP/autodeploy-active.txt" || true
systemctl stop multica-autodeploy.timer multica-autodeploy.path
# Дождаться завершения текущего multica-autodeploy.service, если он активен.
systemctl show multica-autodeploy.service -p ActiveState -p SubState
BASE=/opt/multica
ADDON="$REPO/mcp/multica-tasks/deploy/compose.production.yaml"
sed -e "s/\${MULTICA_MCP_UID:?[^}]*}/$(id -u multica-mcp)/" \
    -e "s/\${MULTICA_MCP_GID:?[^}]*}/$(id -g multica-mcp)/" "$ADDON" \
  | install -m 0644 -o root -g root /dev/stdin "$BASE/docker-compose.mcp.yml"
grep -n 'user:' "$BASE/docker-compose.mcp.yml"   # должно быть <uid>:<gid>
# Список -f сверить с com.docker.compose.project.config_files действующего backend.
compose_mcp() {
  docker compose -p "${COMPOSE_PROJECT:?project from backend labels}" --project-directory "$BASE" \
    -f "$BASE/docker-compose.selfhost.yml" \
    -f "$BASE/docker-compose.v070.override.yml" \
    -f "$BASE/docker-compose.mcp.yml" \
    -f "$BASE/docker-compose.autodeploy.yml" "$@"
}
export MULTICA_TASKS_MCP_IMAGE="$MCP_IMAGE"
compose_mcp config --quiet
# Последний override исключает проверку старого образа из текущего autodeploy override.
printf 'services:\n  multica-tasks-mcp:\n    image: %s\n' "$MCP_IMAGE" > "$SNAP/mcp-probe.yml"
# Пробный экземпляр не использует общий аудит и не занимает порт работающего MCP.
compose_mcp -f "$SNAP/mcp-probe.yml" run -d --no-deps --name stt-454-mcp-probe \
  -e MULTICA_MCP_PORT=18101 -e STATE_DIRECTORY=/tmp/mcp-probe multica-tasks-mcp
docker exec stt-454-mcp-probe python3 -I /app/deploy/probe.py --smoke
docker stop stt-454-mcp-probe
docker rm stt-454-mcp-probe
```

Ожидается `healthz=200; unauthenticated=401; tools=9; bad-origin=403`.
Контейнер ещё не заменяет действующую службу.

Переключение. Закрепление версии — обычный PR в форк `inoisy/multica`: файл
`deploy/autodeploy/mcp-image` со строкой `$MCP_IMAGE` (проверки и слияние —
обычный путь форка). Это отдельный pin-коммит после публикации образа #30:
до его слияния `mcp_service` не включать. Оператор готовит релиз и включает MCP
в автовыкатке; если платформа уже на целевом SHA, MCP всё равно будет запущен:

```sh
# В ветке форка подготовить pin (обычный PR, не правка main на сервере):
printf '%s\n' "$MCP_IMAGE" > deploy/autodeploy/mcp-image
# После merge pin-only коммита STT не запускается автоматически (deploy/**
# в paths-ignore). Запустить существующую сборку и проверить headSha=PIN_SHA:
gh workflow run stt.yml --repo inoisy/multica --ref main
gh run list --repo inoisy/multica --workflow stt.yml --branch main --event workflow_dispatch \
  --limit 5 --json databaseId,headSha,status,conclusion
# При сдвиге main принять новый SHA отдельно. Продолжать после зелёных CI и STT
# на PIN_SHA и публикации образов платформы; dry-run должен выбрать этот SHA.

# 1. План без изменений: в журнале видно mcp=<образ> и три сервиса.
python3 - <<'PY'
import json
p = "/etc/multica-autodeploy/config.json"
c = json.load(open(p))
open(p + ".before-stt-454", "w").write(json.dumps(c))
c["mcp_service"] = "multica-tasks-mcp"
json.dump(c, open(p, "w"), indent=1)
PY
multica-autodeploy run --dry-run
# 2. Освободить порт и сразу выкатить релиз с закреплённым образом.
systemctl stop multica-tasks-mcp.service
systemctl start multica-autodeploy.service
journalctl -u multica-autodeploy -n 50 --no-pager
curl --fail --silent http://127.0.0.1:8101/healthz
compose_mcp exec -T multica-tasks-mcp python3 -I /app/deploy/probe.py --smoke
```

Провал любого шага — раздел 4. Юнит `multica-tasks-mcp.service` пока не удалять.
Восстановить активность timer/path по `autodeploy-active.txt` только после успешной
проверки либо завершённого отката конфигурации. `dry_run` в config.json должен быть
`false` для live-запуска; пробный план его не меняет.

Доказательства для приёмки merge (очищенные журналы `journalctl -u multica-autodeploy`
и `/var/log/multica-autodeploy.jsonl`):

1. Релиз `main` меняет образы backend, frontend и MCP (`start` → `done`,
   `previous_images` в `/var/lib/multica-autodeploy/state.json` содержит MCP).
2. Откат: `multica-autodeploy rollback` возвращает прежние образы. Если MCP
   в предыдущем релизе не было (первый выкат), контейнер MCP остановлен,
   `systemctl start multica-tasks-mcp.service` возвращает старую службу.
3. Smoke коннектора через Caddy из разрешённого адреса (401 без ключа, MCP
   tools/list с ключом) без создания задач и ранов. Внешний `/mcp` с запрещённого
   адреса остаётся 403; ограничение IP не отключать.

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
systemctl stop multica-autodeploy.timer multica-autodeploy.path
# Дождаться неактивного multica-autodeploy.service перед ручным откатом.
cp -a /etc/multica-autodeploy/config.json.before-stt-454 /etc/multica-autodeploy/config.json
compose_mcp stop multica-tasks-mcp
systemctl start multica-tasks-mcp.service
curl --fail --silent http://127.0.0.1:8101/healthz
```

После снятия пакета: сначала остановить compose MCP, затем вернуть архив,
не запуская два процесса на порту 8101:

```sh
systemctl stop multica-autodeploy.timer multica-autodeploy.path
# Дождаться неактивного multica-autodeploy.service перед ручным откатом.
cp -a /etc/multica-autodeploy/config.json.before-stt-454 /etc/multica-autodeploy/config.json
compose_mcp stop multica-tasks-mcp
SNAP=$(cat /var/backups/stt-454-last)
tar -C / -xzpf "$SNAP/legacy.tgz"
systemctl daemon-reload
systemctl enable --now multica-tasks-mcp.service
curl --fail --silent http://127.0.0.1:8101/healthz
```

Восстанавливать enabled/active остальных юнитов по снимку, а не включать canary
вслепую (она была выключена). Актуальный аудит не заменять старой копией;
UID/GID не менялись. Если включали `mcp_service`, вернуть
`/etc/multica-autodeploy/config.json.before-stt-454` до нового запуска таймера и
остановить контейнер MCP (`compose_mcp stop multica-tasks-mcp`), иначе следующий
релиз снова займёт порт. Откат bio — в
`../bio-media-deploy/README.md`. Откат промпта — `prompt-deploy rollback cto.md`,
скилл возвращается из сохранённой копии штатным CLI.
