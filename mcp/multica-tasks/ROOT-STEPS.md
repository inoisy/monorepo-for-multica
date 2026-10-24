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

Claude Code с ноутбука: добавить его адрес в окружение Caddy
(`systemctl edit caddy` → `[Service]` `Environment=MULTICA_MCP_EXTRA_IPS=<ip>/32`), `systemctl restart caddy`.
По умолчанию переменная пуста, и пускают только `160.79.104.0/21` (облако Anthropic).

Проверка с любого не-Anthropic адреса (ожидаем 403):

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://multica.yakutov.com/mcp
```

Ответ «с разрешённого адреса без ключа — 401» увидит только запрос из облака Anthropic; локально его можно воспроизвести,
временно задав `MULTICA_MCP_EXTRA_IPS` адресом проверяющей машины.

## Шаг 7. Политика harness-control (root)

Пакет harness-control ставится заново с новой политикой и проверкой, затем записывается baseline.

```sh
cd $REPO/services/harness-control
bash bootstrap/install.sh --check        # план и SHA256 пакета; ничего не меняет
bash bootstrap/install.sh --upgrade
/usr/local/sbin/harness-priv adopt-baseline multica-tasks-mcp
harness-control inspect multica-tasks-mcp   # дрейфа нет, health ok
```

## Шаг 8. Подключить коннектор

`CONNECT.md`: адрес `https://multica.yakutov.com/mcp`, заголовок `Authorization: Bearer <ключ из шага 4>`.

## Откат

```sh
# убрать блок @mcp из Caddyfile (копия в Caddyfile.bak-*), затем:
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && systemctl reload caddy
systemctl disable --now multica-tasks-mcp.service
```

Затем отозвать PAT в Multica. Файлы и пользователь `multica-mcp` можно оставить.
