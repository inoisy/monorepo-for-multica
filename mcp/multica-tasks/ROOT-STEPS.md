# Разовые шаги оператора

После слияния PR. Агентам эти шаги недоступны (нужен root и вход под сервисным пользователем). Дальше обновления идут
через `harness-control validate/deploy` без оператора. `$REPO` — клон монорепо на коммите из `main`.

Отличие от плана: порт сервиса `8101`, а не `8099`: `8099` уже занят сервисом `/takes/*` (проверено `ss -ltn` и Caddyfile).

## Шаг 1. Сервисный пользователь в Multica (не root)

1. Завести учётную запись «Claude (MCP)» на почту, к которой есть доступ (вход по коду из письма).
2. Добавить её **member** (не admin) в воркспейсы, которые должен видеть коннектор. Минимум `stt`.
3. Войти под ней, создать PAT на 90 дней (Settings → Tokens). Токен показывается один раз; пригодится в шаге 4.

## Шаг 2. Пользователь и каталоги (root)

```sh
useradd --system --no-create-home --shell /usr/sbin/nologin multica-mcp
install -d -o root -g root -m 0755 /usr/local/lib/multica-tasks-mcp /usr/local/lib/multica-tasks-mcp/bin \
  /usr/local/lib/multica-tasks-mcp/multica_tasks /etc/multica-tasks-mcp
```

## Шаг 3. Файлы первого релиза (root)

Дальше их обновляет harness-control; baseline для отката запишется в шаге 7.

```sh
SRC=$REPO/mcp/multica-tasks; DST=/usr/local/lib/multica-tasks-mcp
install -o root -g root -m 0755 "$SRC/bin/multica-tasks-mcp" "$DST/bin/multica-tasks-mcp"
for f in "$SRC"/multica_tasks/*.py; do install -o root -g root -m 0644 "$f" "$DST/multica_tasks/$(basename "$f")"; done
install -o root -g root -m 0644 "$SRC/systemd/multica-tasks-mcp.service" /etc/systemd/system/multica-tasks-mcp.service
```

## Шаг 4. Секреты (root)

Ключ коннектора генерируется здесь и показывается один раз; PAT вводится без эха.

```sh
umask 077
KEY=$(openssl rand -hex 32)
read -rsp 'PAT сервисного пользователя: ' PAT; echo
cat > /etc/multica-tasks-mcp/env <<ENV
MULTICA_MCP_KEY=$KEY
MULTICA_PAT=$PAT
MULTICA_API_URL=http://127.0.0.1:8080
MULTICA_MCP_WORKSPACES=stt
ENV
chown root:root /etc/multica-tasks-mcp/env; chmod 0600 /etc/multica-tasks-mcp/env
echo "Ключ для claude.ai (запишите, повторно не показывается): $KEY"; unset KEY PAT
```

Список воркспейсов — slug через запятую (`stt,toons,sirius-qi2i`); пользователь «Claude (MCP)» должен быть в них членом.
Для личных ключей добавить в env строку `MULTICA_MCP_CLIENTS=/etc/multica-tasks-mcp/clients.json` (шаг 8). Сервису нужен бинарь
`/usr/local/bin/multica` (в образе он есть; для systemd-установки — тот же, что у агентов).

## Шаг 5. Запуск (root)

```sh
systemctl daemon-reload
systemctl enable --now multica-tasks-mcp.service
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8101/healthz     # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8101/mcp  # 401
journalctl -u multica-tasks-mcp -n 20 --no-pager
```

## Шаг 6. Caddy (root)

Вставить `$REPO/mcp/multica-tasks/deploy/Caddyfile.fragment` (без комментариев в начале) в блок `multica.yakutov.com`
в `/etc/caddy/Caddyfile`: перед последней строкой `reverse_proxy 127.0.0.1:3000`, рядом с `/control`.

```sh
cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d)
$EDITOR /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && systemctl reload caddy
```

IP-фильтра нет (снят 29.10.2026): вход только по Bearer-ключу, который проверяет сервис. Проверка без ключа (ожидаем 401):

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://multica.yakutov.com/mcp
```

## Шаг 7. Политика harness-control (root)

Пакет harness-control ставится заново с новой политикой и проверкой, затем записывается baseline.

```sh
cd $REPO/services/harness-control
bash bootstrap/install.sh --check        # план и SHA256 пакета; ничего не меняет
bash bootstrap/install.sh --upgrade
/usr/local/sbin/harness-priv adopt-baseline multica-tasks-mcp
harness-control inspect multica-tasks-mcp   # дрейфа нет, health ok
```

## Шаг 8. Личные ключи сотрудников (root)

Файл клиентов читает сам сервис: владелец — UID/GID контейнера (`MULTICA_MCP_UID:MULTICA_MCP_GID`), права `0600`,
иначе сервис не стартует. Если юнит старый (systemd) — владелец `multica-mcp`.

Контейнер (`multica-autodeploy`): этот шаг — до закрепления нового образа в `deploy/autodeploy/mcp-image` форка. Порядок:
1) создать `clients.json` (скрипт ниже) — иначе Docker при старте создаст на месте файла каталог; 2) обновить root-копию
`/opt/multica/docker-compose.mcp.yml` по `deploy/compose.production.yaml` этого коммита, сохранив строку `user:` из
действующей копии (tmpfs `/run/multica-cli`, `MULTICA_MCP_RUN_DIR`, монтирование `clients.json`); 3) добавить строку
`MULTICA_MCP_CLIENTS` в env. Без шагов 2–3 новый образ работает только с клиентом по умолчанию.

```sh
umask 077
read -rsp 'PAT сотрудника (mul_…): ' EMP_PAT; echo
EMP_KEY=$(openssl rand -hex 32)
FILE=/etc/multica-tasks-mcp/clients.json
[ -d "$FILE" ] && rmdir "$FILE"   # каталог, который создал Docker при старте без файла
[ -f "$FILE" ] || echo '[]' > "$FILE"
cp -a "$FILE" "$FILE.bak-$(date +%Y%m%d%H%M%S)"
NAME='Илья' KEY="$EMP_KEY" PAT="$EMP_PAT" WS='stt' FILE="$FILE" python3 -I - <<'PY'
import json, os
rows = json.load(open(os.environ['FILE']))
rows.append({'name': os.environ['NAME'], 'key': os.environ['KEY'], 'token': os.environ['PAT'], 'workspaces': [os.environ['WS']]})
json.dump(rows, open(os.environ['FILE'], 'w'), ensure_ascii=False, indent=2)
PY
chown "$(stat -c '%u:%g' /var/lib/multica-tasks-mcp)" "$FILE"; chmod 0600 "$FILE"
echo "Ключ для сотрудника (повторно не показывается): $EMP_KEY"; unset EMP_KEY EMP_PAT
```

В `/etc/multica-tasks-mcp/env` должна быть строка `MULTICA_MCP_CLIENTS=/etc/multica-tasks-mcp/clients.json`. Файл читается
на старте, поэтому перезапустить сервис: контейнер — `compose_mcp up -d --force-recreate --no-deps multica-tasks-mcp`
(`compose_mcp` — из `services/harness-retire/README.md`; обычный `up -d` при изменении одного `clients.json` контейнер не
пересоздаёт), systemd — `systemctl restart multica-tasks-mcp`.

Проверка: из Claude Code сотрудника `{"args": ["issue", "get", "TST-123"]}`; запрещённая команда `{"args": ["agent", "update", "x"]}`
даёт отказ «только по ssh»; в `/var/lib/multica-tasks-mcp/audit.jsonl` появляются записи с `"client": "Илья"`, среди них один
отказ (`"denied"` не `null`):

```sh
grep '"client": "Илья"' /var/lib/multica-tasks-mcp/audit.jsonl | tail -3
```

Откат: `cp clients.json.bak-* clients.json` (копией, не `mv`: файл смонтирован в контейнер) и перезапустить сервис той же
командой; клиент по умолчанию работает и с пустым `[]`.

## Шаг 9. Подключить коннектор

`CONNECT.md`: адрес `https://multica.yakutov.com/mcp`, заголовок `Authorization: Bearer <ключ из шага 4>`.

## Откат

```sh
# убрать блок @mcp из Caddyfile (копия в Caddyfile.bak-*), затем:
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && systemctl reload caddy
systemctl disable --now multica-tasks-mcp.service
```

Затем отозвать PAT в Multica. Файлы и пользователь `multica-mcp` можно оставить.
