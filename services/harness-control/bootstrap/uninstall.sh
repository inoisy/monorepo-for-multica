#!/usr/bin/env bash
# Снятие harness-control оператором (root). Первым удаляется sudoers: агент теряет доступ до любых других действий.
#   uninstall.sh                     файлы и юниты снимаются, выложенные через harness версии остаются как есть
#   uninstall.sh --restore-baseline  перед снятием компоненты возвращаются на baseline (файлы, найденные при установке)
# Состояние и политика уходят в /var/backups/harness-control-<время>, а не удаляются.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Нужен root' >&2; exit 1; }
RESTORE=0
[[ ${1:-} == --restore-baseline ]] && RESTORE=1

LIB=/usr/local/lib/harness-control
BACKUP=/var/backups/harness-control-$(date +%Y%m%d-%H%M%S)

echo '1. доступ агента'
rm -f /etc/sudoers.d/harness-control

if [[ $RESTORE == 1 ]]; then
  echo '2. возврат компонентов на baseline'
  for policy in /etc/harness-control/policy.d/*.json; do
    c=$(basename "$policy" .json)
    out=$(/usr/local/sbin/harness-priv rollback "$c" --to baseline --reason 'uninstall --restore-baseline' || true)
    op=$(printf '%s' "$out" | python3 -I -c 'import json,sys; print(json.load(sys.stdin).get("operation_id",""))' 2>/dev/null || true)
    if [[ -z $op ]]; then echo "  $c: $out"; continue; fi
    for _ in $(seq 1 180); do
      status=$(/usr/local/sbin/harness-priv op "$op" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["status"])')
      case $status in done|failed|degraded|interrupted|rolled_back) break ;; esac
      sleep 5
    done
    echo "  $c: $status"
  done
fi

echo '3. юниты'
systemctl disable --now harness-control-recover.service harness-canary.timer 2>/dev/null || true
rm -f /etc/systemd/system/harness-control-recover.service /etc/systemd/system/harness-canary.service /etc/systemd/system/harness-canary.timer
systemctl daemon-reload

echo "4. состояние → $BACKUP"
install -d -m 0700 "$BACKUP"
[[ -d /var/lib/harness-control ]] && mv /var/lib/harness-control "$BACKUP/state"
[[ -d /etc/harness-control ]] && mv /etc/harness-control "$BACKUP/etc"

echo '5. файлы'
rm -f /usr/local/sbin/harness-priv /usr/local/bin/harness-control /usr/local/bin/harness-control-mcp
rm -rf "$LIB"
echo 'готово. multica-provider.timer и установленные через harness версии не тронуты; baseline восстановлен только с --restore-baseline.'
