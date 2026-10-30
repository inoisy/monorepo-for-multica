#!/usr/bin/env bash
# STT-506, ROOT-STEPS.md шаг «Вход через OAuth»: ключ шифрования, compose, Caddy, проверка. Запускается от root на хосте marcelle.
#   sudo bash /home/agents/ops/stt-506/apply.sh                подготовить; если образ уже с OAuth — включить маршруты Caddy и проверить
#   sudo bash /home/agents/ops/stt-506/apply.sh --check        только проверки, ничего не меняет
#   sudo bash /home/agents/ops/stt-506/apply.sh --rollback /root/mcp-oauth/<stamp>
#   bash /home/agents/ops/stt-506/apply.sh --verify-only [URL]   публичная проверка OAuth (root не нужен; URL по умолчанию — боевой)
# Идемпотентен: после выкатки образа autodeploy запустить ту же команду ещё раз. Состояния:
#   ПОДГОТОВЛЕНО — ключ, compose и env готовы, образ в контейнере ещё без OAuth: Caddy и контейнер не трогаются;
#   ВКЛЮЧЕНО     — образ с OAuth: Caddy переключён, контейнер пересоздан, публичная проверка пройдена.
# Сбой после первого изменения — автоматический откат из бэкапа. Ключ и oauth.sqlite откатом не удаляются.
set -euo pipefail
umask 077

MODE=apply
ROLLBACK_DIR=
VERIFY_BASE=
while (( $# )); do
  case "$1" in
    --check) MODE=check; shift ;;
    --rollback) MODE=rollback; ROLLBACK_DIR=${2:?каталог бэкапа}; shift 2 ;;
    --verify-only) MODE=verify; VERIFY_BASE=${2:-}; [[ $# -ge 2 ]] && shift 2 || shift ;;
    *) echo "usage: $0 [--check] [--rollback DIR] [--verify-only [URL]]" >&2; exit 2 ;;
  esac
done

ETC=/etc/multica-tasks-mcp
ENV_FILE=$ETC/env
CLIENTS=$ETC/clients.json
KEY_FILE=$ETC/oauth.key
BASE=/opt/multica
MCP_YML=$BASE/docker-compose.mcp.yml
STATE=/var/lib/multica-tasks-mcp
CADDYFILE=/etc/caddy/Caddyfile
SVC=multica-tasks-mcp
PORT=8101
PUBLIC=https://multica.yakutov.com
BACKUPS=/root/mcp-oauth          # env, compose, Caddyfile, clients.json
KEY_BACKUPS=/root/mcp-oauth-keys # только ключ шифрования — отдельно от БД
DB_BACKUPS=/root/mcp-oauth-db    # только oauth.sqlite — отдельно от ключа
CLIENTS_LINE="MULTICA_MCP_CLIENTS=$CLIENTS"

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
fail() { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }

# --- публичная проверка (root не нужен) ---------------------------------------------------------------------------
verify() {  # $1 — базовый адрес; MCP_VERIFY_LOGIN=0 пропускает проверку, что /login отдаёт Multica (локальный прогон)
  MCP_VERIFY_BASE=$1 python3 -I - <<'PY'
import base64, hashlib, http.client, json, os, re, secrets, ssl, sys
from urllib.parse import urlsplit, quote

base = os.environ['MCP_VERIFY_BASE'].rstrip('/')
u = urlsplit(base)
resource = base + '/mcp'
ok = True

def call(method, path, body=None, headers=None):
    conn = (http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=15, context=ssl.create_default_context())
            if u.scheme == 'https' else http.client.HTTPConnection(u.hostname, u.port or 80, timeout=15))
    try:
        conn.request(method, path, body, headers or {})
        r = conn.getresponse()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read()
    finally:
        conn.close()

def check(name, cond, detail=''):
    global ok
    print(('  ok   ' if cond else '  FAIL ') + name + ('' if cond else f'  [{detail}]'))
    ok = ok and bool(cond)

s, h, _ = call('POST', '/mcp', '{}', {'Content-Type': 'application/json'})
check('POST /mcp без токена → 401 с resource_metadata', s == 401 and f'resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"' in h.get('www-authenticate', ''), f'{s} {h.get("www-authenticate")}')
for path in ('/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-protected-resource'):
    s, _, d = call('GET', path)
    meta = json.loads(d) if s == 200 else {}
    check(f'GET {path}', s == 200 and meta.get('resource') == resource and meta.get('authorization_servers') == [base], s)
s, _, d = call('GET', '/.well-known/oauth-authorization-server')
meta = json.loads(d) if s == 200 else {}
check('GET /.well-known/oauth-authorization-server', s == 200 and meta.get('issuer') == base
      and meta.get('code_challenge_methods_supported') == ['S256'] and meta.get('registration_endpoint') == base + '/mcp/oauth/register'
      and meta.get('token_endpoint') == base + '/mcp/oauth/token', s)
redirect = 'https://claude.ai/api/mcp/auth_callback'
reg = {'client_name': 'STT-506 проверка выкатки', 'redirect_uris': [redirect], 'grant_types': ['authorization_code', 'refresh_token'],
       'response_types': ['code'], 'token_endpoint_auth_method': 'none'}
s, _, d = call('POST', '/mcp/oauth/register', json.dumps(reg), {'Content-Type': 'application/json'})
if s == 429:
    print('  WARN регистрация: лимит 20/час с адреса — шаги authorize/continue пропущены, повторить позже')
else:
    client = json.loads(d).get('client_id') if s == 201 else None
    check('POST /mcp/oauth/register → 201 с client_id', bool(client), s)
    if client:
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        q = (f'response_type=code&client_id={quote(client)}&redirect_uri={quote(redirect, safe="")}&code_challenge={challenge}'
             f'&code_challenge_method=S256&resource={quote(resource, safe="")}&scope=multica&state=check')
        s, _, d = call('GET', '/mcp/oauth/authorize?' + q)
        m = re.search(rb'/mcp/oauth/continue\?req=[A-Za-z0-9_%.~-]+', d) if s == 200 else None
        check('GET /mcp/oauth/authorize → страница с переходом на continue', bool(m), s)
        if m:
            s, h, _ = call('GET', m.group(0).decode().replace('&amp;', '&'))
            check('GET continue без сессии → редирект на /login?next=', s in (302, 303) and '/login?next=' in h.get('location', ''), f'{s} {h.get("location")}')
        s, h, _ = call('GET', '/mcp/oauth/authorize?' + q.replace('code_challenge_method=S256', 'code_challenge_method=plain'))
        check('authorize с PKCE plain отклоняется (error=invalid_request)', s in (302, 303) and 'error=invalid_request' in h.get('location', ''), f'{s} {h.get("location")}')
if os.environ.get('MCP_VERIFY_LOGIN', '1') == '1':
    s, h, d = call('GET', '/login')
    check('GET /login отвечает Multica (HTML, не сервис MCP)', s == 200 and 'text/html' in h.get('content-type', '') and h.get('server', '') != 'multica-tasks-mcp', f'{s} {h.get("server")}')
print('ИТОГ: ' + ('все проверки пройдены' if ok else 'есть ошибки'))
sys.exit(0 if ok else 1)
PY
}

if [[ $MODE == verify ]]; then
  step "Публичная проверка ${VERIFY_BASE:-$PUBLIC}"
  verify "${VERIFY_BASE:-$PUBLIC}"
  exit $?
fi

[[ $(id -u) == 0 ]] || fail "нужен root: sudo bash $0"

# --- docker compose тем же проектом и файлами, что у действующего контейнера --------------------------------------
CID=$(docker ps -q --filter "label=com.docker.compose.service=$SVC" | head -1)
[[ -n $CID ]] || fail "контейнер $SVC не запущен"
PROJECT=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$CID")
CONFIG_FILES=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$CID")
WORKDIR=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$CID")
IMAGE=$(docker inspect -f '{{.Config.Image}}' "$CID")
OWNER=$(stat -c '%u:%g' "$STATE")
[[ -n $PROJECT && -n $CONFIG_FILES ]] || fail 'нет compose-меток у контейнера'
COMPOSE_ARGS=(-p "$PROJECT" --project-directory "${WORKDIR:-$BASE}")
IFS=',' read -ra _files <<<"$CONFIG_FILES"
for f in "${_files[@]}"; do [[ -f $f ]] || fail "нет файла compose: $f"; COMPOSE_ARGS+=(-f "$f"); done
[[ ,$CONFIG_FILES, == *",$MCP_YML,"* ]] || fail "$MCP_YML не входит в compose-проект ($CONFIG_FILES)"
compose() { MULTICA_TASKS_MCP_IMAGE="$IMAGE" docker compose "${COMPOSE_ARGS[@]}" "$@"; }

image_has_oauth() { docker exec "$CID" test -f /app/multica_tasks/oauth_service.py 2>/dev/null; }

recreate() { compose up -d --force-recreate --no-deps "$SVC"; }

wait_healthy() {
  local i code
  for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/healthz" || true)
    [[ $code == 200 ]] && return 0
    sleep 1
  done
  return 1
}

# Блок Caddy — тот же, что deploy/Caddyfile.fragment в репозитории (между маркерами включительно, один таб отступа).
caddy_block() {
  cat <<'CADDY'
	# >>> multica-tasks-mcp (STT-272, STT-506)
	@mcp path /mcp /mcp/oauth/* /.well-known/oauth-protected-resource /.well-known/oauth-protected-resource/mcp /.well-known/oauth-authorization-server
	handle @mcp {
		request_body {
			max_size 1MB
		}
		# Адрес клиента для аудита: заголовок задаёт Caddy, присланное клиентом не принимаем
		reverse_proxy 127.0.0.1:8101 {
			header_up X-Forwarded-For {remote_host}
		}
	}
	# <<< multica-tasks-mcp
CADDY
}

# Печатает новый Caddyfile (старый из $1) со вставленным блоком; ошибка, если маркеров не ровно по одному.
caddy_render() {
  BLOCK=$(caddy_block) SRC=$1 python3 -I - <<'PY'
import os, re, sys
text = open(os.environ['SRC'], encoding='utf-8').read()
start = re.findall(r'^[ \t]*# >>> multica-tasks-mcp.*$', text, re.M)
end = re.findall(r'^[ \t]*# <<< multica-tasks-mcp[ \t]*$', text, re.M)
if len(start) != 1 or len(end) != 1:
    sys.exit('в Caddyfile должны быть ровно по одному маркеру >>> и <<< multica-tasks-mcp')
pattern = re.compile(r'^[ \t]*# >>> multica-tasks-mcp.*?^[ \t]*# <<< multica-tasks-mcp[ \t]*$', re.M | re.S)
sys.stdout.write(pattern.sub(lambda m: os.environ['BLOCK'], text, count=1))
PY
}

mcp_yml() {  # $1 — строка user: из действующей копии. Совпадает с deploy/compose.production.yaml в коммите задачи.
  cat <<YML
# Installed by the operator as /opt/multica/docker-compose.mcp.yml (see
# services/harness-retire/README.md); multica-autodeploy includes it and sets the
# image from deploy/autodeploy/mcp-image of the released commit. Stand uses ../compose.yaml.
services:
  multica-tasks-mcp:
    image: \${MULTICA_TASKS_MCP_IMAGE:-multica-tasks-mcp:set-by-autodeploy}
$1
    network_mode: host
    env_file: /etc/multica-tasks-mcp/env
    environment:
      MULTICA_MCP_HOST: 127.0.0.1
      MULTICA_MCP_PORT: "8101"
      STATE_DIRECTORY: /state
      MULTICA_MCP_RUN_DIR: /run/multica-cli
      # Вход через OAuth (STT-506): ключ шифрования выданных PAT. Файл создаёт скрипт оператора (ROOT-STEPS.md) до пересоздания.
      MULTICA_MCP_OAUTH_KEY_FILE: /etc/multica-tasks-mcp/oauth.key
      MULTICA_MCP_PUBLIC_URL: https://multica.yakutov.com
    volumes:
      - /var/lib/multica-tasks-mcp:/state
      # Файл клиентов: владелец — UID/GID сервиса, 0600 (ROOT-STEPS.md, шаг «Личные ключи»)
      - /etc/multica-tasks-mcp/clients.json:/etc/multica-tasks-mcp/clients.json:ro
      # Ключ Fernet: владелец — UID/GID сервиса, 0600, вне каталога состояния (рядом с oauth.sqlite его хранить нельзя)
      - /etc/multica-tasks-mcp/oauth.key:/etc/multica-tasks-mcp/oauth.key:ro
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=16m
      - /run/multica-cli:rw,noexec,nosuid,size=16m,mode=1777
    mem_limit: 256m
    pids_limit: 64
    restart: unless-stopped
    stop_grace_period: 15s
YML
}

restore() {  # $1 — каталог бэкапа. Ключ и oauth.sqlite не трогаем.
  local dir=$1
  [[ -f $dir/env ]] && cat "$dir/env" > "$ENV_FILE"
  [[ -f $dir/docker-compose.mcp.yml ]] && cat "$dir/docker-compose.mcp.yml" > "$MCP_YML"
  if [[ -f $dir/clients.json ]]; then cat "$dir/clients.json" > "$CLIENTS"; fi
  if [[ -f $dir/Caddyfile ]] && ! cmp -s "$dir/Caddyfile" "$CADDYFILE"; then
    cp -a "$dir/Caddyfile" "$CADDYFILE"
    caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1 && systemctl reload caddy || say 'откат: Caddyfile не прошёл validate — смотреть вручную'
  fi
  recreate
  wait_healthy && say 'откат: сервис поднят (healthz=200)' || say 'откат: healthz не 200 — docker logs'
}

if [[ $MODE == rollback ]]; then
  [[ -d $ROLLBACK_DIR ]] || fail "нет каталога $ROLLBACK_DIR"
  step "Откат из $ROLLBACK_DIR"
  restore "$ROLLBACK_DIR"
  say 'Ключ и oauth.sqlite сохранены. OAuth отключён: контейнер снова с прежним compose, Caddy без маршрутов OAuth.'
  exit 0
fi

# --- проверки ------------------------------------------------------------------------------------------------------
step 'Проверки'
say "контейнер:   $CID ($IMAGE)"
say "владелец:    $OWNER (из $STATE)"
USER_LINE=$(grep -m1 '^    user:' "$MCP_YML" || true)
[[ -n $USER_LINE ]] || fail "нет строки user: в $MCP_YML"
say "user в mcp.yml: ${USER_LINE//    /}"
[[ $USER_LINE == "    user: $OWNER" ]] || say "ВНИМАНИЕ: user: в compose не совпадает с владельцем $STATE ($OWNER); user: сохраняется как есть"
[[ $(systemctl show multica-autodeploy.service -p ActiveState --value) != active ]] \
  || fail 'идёт multica-autodeploy — дождаться окончания и запустить снова'
if image_has_oauth; then IMAGE_READY=1; say 'образ: с OAuth (oauth_service.py есть)'; else IMAGE_READY=0; say 'образ: ещё без OAuth — будет только подготовка'; fi
[[ -f $ENV_FILE ]] || fail "нет $ENV_FILE"
[[ -f $KEY_FILE ]] && say "ключ: $KEY_FILE уже есть (не перезаписывается)" || say "ключ: будет создан $KEY_FILE"
[[ -d $CLIENTS ]] && say "clients.json: на месте файла каталог (создал Docker) — будет заменён файлом" || true
caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1 && say 'Caddyfile: validate ok' || fail 'текущий Caddyfile не проходит caddy validate'
caddy_render "$CADDYFILE" > /dev/null || fail 'Caddyfile: маркеры блока multica-tasks-mcp'
NEW_CADDY=$(mktemp); trap 'rm -f "$NEW_CADDY"' EXIT
caddy_render "$CADDYFILE" > "$NEW_CADDY"
caddy validate --config "$NEW_CADDY" --adapter caddyfile >/dev/null 2>&1 && say 'Caddyfile с новым блоком: validate ok' || fail 'Caddyfile с новым блоком не проходит caddy validate'
cmp -s "$NEW_CADDY" "$CADDYFILE" && say 'Caddy: блок уже актуален' || say 'Caddy: блок будет заменён'
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/me || true)
[[ $code == 401 ]] && say 'Multica API на 127.0.0.1:8080: 401 без сессии (доступна)' || fail "Multica API на 127.0.0.1:8080 отвечает $code (ожидали 401)"
tmp_mcp=$(mktemp); mcp_yml "$USER_LINE" > "$tmp_mcp"
cmp -s "$tmp_mcp" "$MCP_YML" && say 'compose: уже актуален' || say 'compose: будет заменён (тот же user:, добавлены OAuth-ключ и публичный адрес)'
rm -f "$tmp_mcp"
[[ $MODE == check ]] && { say; say 'Проверки пройдены, изменений нет.'; exit 0; }

# --- бэкап ---------------------------------------------------------------------------------------------------------
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=$BACKUPS/$STAMP
install -d -m 0700 "$BACKUPS" "$KEY_BACKUPS" "$DB_BACKUPS" "$BACKUP"
cp -a "$ENV_FILE" "$BACKUP/env"
cp -a "$MCP_YML" "$BACKUP/docker-compose.mcp.yml"
cp -a "$CADDYFILE" "$BACKUP/Caddyfile"
[[ -f $CLIENTS ]] && cp -a "$CLIENTS" "$BACKUP/clients.json"
if [[ -f $STATE/oauth.sqlite ]]; then
  python3 -I - "$STATE/oauth.sqlite" "$DB_BACKUPS/oauth-$STAMP.sqlite" <<'PY'
import sqlite3, sys
src = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
  chmod 0600 "$DB_BACKUPS/oauth-$STAMP.sqlite"
  say "бэкап oauth.sqlite: $DB_BACKUPS/oauth-$STAMP.sqlite"
fi
step "Бэкап: $BACKUP"

CHANGED=0
on_exit() {
  local rc=$?
  rm -f "${NEW_CADDY:-}"
  if (( rc != 0 && CHANGED == 1 )); then
    printf '\nСбой — откат из %s\n' "$BACKUP" >&2
    restore "$BACKUP" >&2 || printf 'откат не удался: sudo bash %s --rollback %s\n' "$0" "$BACKUP" >&2
  fi
  exit "$rc"
}
trap on_exit EXIT
CHANGED=1

# --- ключ, clients.json, env, compose -------------------------------------------------------------------------------
step 'Ключ шифрования'
if [[ ! -f $KEY_FILE ]]; then
  head -c 32 /dev/urandom | base64 -w0 | tr '+/' '-_' > "$KEY_FILE"
  say 'создан новый ключ'
else
  say 'ключ уже есть — не перезаписан (иначе выданные PAT станет невозможно расшифровать)'
fi
chown "$OWNER" "$KEY_FILE"; chmod 0600 "$KEY_FILE"
# Копия ключа — в отдельный каталог, не рядом с БД; копия только если такого ключа там ещё нет
KEY_SUM=$(sha256sum "$KEY_FILE" | cut -c1-16)
[[ -f $KEY_BACKUPS/oauth-$KEY_SUM.key ]] || { cp -a "$KEY_FILE" "$KEY_BACKUPS/oauth-$KEY_SUM.key"; chown root:root "$KEY_BACKUPS/oauth-$KEY_SUM.key"; chmod 0400 "$KEY_BACKUPS/oauth-$KEY_SUM.key"; }
ls -l "$KEY_FILE"; say "копия ключа: $KEY_BACKUPS/oauth-$KEY_SUM.key"

step 'clients.json и env'
[[ -d $CLIENTS ]] && rmdir "$CLIENTS"
[[ -f $CLIENTS ]] || echo '[]' > "$CLIENTS"
chown "$OWNER" "$CLIENTS"; chmod 0600 "$CLIENTS"
grep -qxF "$CLIENTS_LINE" "$ENV_FILE" || printf '%s\n' "$CLIENTS_LINE" >> "$ENV_FILE"
say 'clients.json на месте, MULTICA_MCP_CLIENTS задан'

step 'docker-compose.mcp.yml'
mcp_yml "$USER_LINE" > "$MCP_YML"; chmod 0644 "$MCP_YML"
compose config --quiet
say 'записан, compose config ok'

if (( IMAGE_READY == 0 )); then
  CHANGED=0; trap - EXIT
  step 'ПОДГОТОВЛЕНО'
  say 'Ключ, compose и env готовы. Контейнер и Caddy не менялись: образ ещё без OAuth.'
  say 'Дальше: слить PR 33 и pin-PR образа, дождаться multica-autodeploy, затем запустить ТУ ЖЕ команду ещё раз.'
  say "Откат подготовки: sudo bash $0 --rollback $BACKUP"
  exit 0
fi

# --- включение -----------------------------------------------------------------------------------------------------
step 'Контейнер'
recreate
wait_healthy || { docker logs --tail 20 "$(compose ps -q "$SVC")" >&2 || true; fail 'healthz не 200 за 30 с'; }
say 'healthz=200'
NEWCID=$(compose ps -q "$SVC")
docker logs --tail 50 "$NEWCID" 2>&1 | grep -q 'конфигурация:' && { docker logs --tail 20 "$NEWCID" >&2; fail 'сервис сообщил об ошибке конфигурации'; } || true

step 'Caddy'
caddy_render "$CADDYFILE" > "$NEW_CADDY"
caddy validate --config "$NEW_CADDY" --adapter caddyfile >/dev/null
cat "$NEW_CADDY" > "$CADDYFILE"
caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null
systemctl reload caddy
sleep 1
say 'Caddy перечитан'

step 'Публичная проверка'
verify "$PUBLIC"

CHANGED=0; trap - EXIT; rm -f "$NEW_CADDY"
step 'ВКЛЮЧЕНО'
say "Бэкап: $BACKUP"
say "Откат: sudo bash $0 --rollback $BACKUP"
say 'Осталось (руками, нужен браузер): подключить коннектор и сделать issue get — ROOT-STEPS.md, шаг «Проверка выкатки».'
say 'Журнал входа: sudo bash /home/agents/ops/stt-506/status.sh'
