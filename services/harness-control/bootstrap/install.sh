#!/usr/bin/env bash
# Установка и обновление harness-control оператором (root).
#   install.sh --check     план и SHA256 пакета, без root, ничего не меняет
#   install.sh             первая установка
#   install.sh --upgrade   обновление пакета; состояние, операции и baseline сохраняются
# План печатается теми же командами, которые затем выполняются, поэтому --check показывает ровно то, что будет сделано.
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PKG=$(dirname -- "$HERE")
MODE=install
case "${1:-}" in
  --check) MODE=check ;;
  --upgrade) MODE=upgrade ;;
  '') ;;
  *) echo "usage: install.sh [--check|--upgrade]" >&2; exit 2 ;;
esac

LIB=/usr/local/lib/harness-control
ETC=/etc/harness-control
STATE=/var/lib/harness-control
SYSTEMD=/etc/systemd/system
SUDOERS=/etc/sudoers.d/harness-control
UNITS_SRC=$PKG/units
[[ -d $UNITS_SRC ]] || UNITS_SRC=$(dirname -- "$PKG")/multica-conveyor/systemd
COMPONENTS=(harness-canary multica-conveyor)

run() {
  local shown="$*"
  printf '  %s\n' "${shown//$PKG/<пакет>}"
  if [[ $MODE != check ]]; then "$@"; fi
}

# Список файлов пакета (относительно $PKG), по нему считается SHA256 и ставятся файлы.
package_files() {
  (cd "$PKG" && find harness_control bin checks policy.d canary bootstrap VERSION -type f \
      ! -path '*/__pycache__/*' ! -name '*.pyc' ! -path 'canary/tests/*' | LC_ALL=C sort)
}
unit_files() { printf '%s\n' multica-provider.service multica-provider.timer; }
package_sha() {
  {
    (cd "$PKG" && package_files_sha)
    for u in $(unit_files); do printf '%s  units/%s\n' "$(sha256sum "$UNITS_SRC/$u" | cut -d' ' -f1)" "$u"; done
  } | LC_ALL=C sort -k2 | sha256sum | cut -d' ' -f1
}
package_files_sha() { package_files | while read -r f; do printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"; done; }

if [[ -f $PKG/MANIFEST.sha256 ]]; then
  (cd "$PKG" && sha256sum --quiet -c MANIFEST.sha256) || { echo 'MANIFEST.sha256 не сходится: пакет изменён' >&2; exit 1; }
fi

echo "harness-control install ($MODE)"
echo "пакет: $PKG"
echo "версия: $(cat "$PKG/VERSION")"
echo "SHA256 пакета: $(cd "$PKG" && package_sha)"
[[ $MODE == check ]] && echo 'режим --check: root не нужен, ничего не меняется'
echo 'план:'

if [[ $MODE != check ]]; then
  [[ $(id -u) == 0 ]] || { echo 'Нужен root: sudo bash '"$HERE"'/install.sh' >&2; exit 1; }
  command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
    || { echo 'нужен python3 >= 3.12' >&2; exit 1; }
  id agents >/dev/null 2>&1 || { echo 'нет пользователя agents' >&2; exit 1; }
  /usr/sbin/visudo -cf "$HERE/sudoers.harness-control" >/dev/null
  if [[ $MODE == install && -e $ETC ]]; then
    echo "$ETC уже существует: для обновления запустите install.sh --upgrade" >&2; exit 1
  fi
  if systemctl list-units --no-legend --state=active 'harness-op-*' 2>/dev/null | grep -q .; then
    echo 'идёт операция harness-control; дождитесь завершения и повторите' >&2; exit 1
  fi
  for u in $(unit_files); do
    if [[ -e $SYSTEMD/$u ]] && ! cmp -s "$UNITS_SRC/$u" "$SYSTEMD/$u"; then
      echo "$SYSTEMD/$u отличается от пакета; проверьте вручную" >&2; exit 1
    fi
  done
fi

# --- каталоги -----------------------------------------------------------------------------
for d in "$LIB" "$LIB/bin" "$ETC" "$ETC/policy.d"; do run install -d -o root -g root -m 0755 "$d"; done
run install -d -o root -g root -m 0700 "$STATE"

# --- код пакета (корень: root:root, без записи другим) --------------------------------------
while read -r f; do
  case $f in
    bootstrap/*|policy.d/*|VERSION) continue ;;
  esac
  mode=0644
  [[ -x $PKG/$f ]] && mode=0755
  run install -D -o root -g root -m "$mode" "$PKG/$f" "$LIB/$f"
done < <(package_files)
run install -o root -g root -m 0644 "$PKG/VERSION" "$LIB/VERSION"
run install -o root -g root -m 0755 "$HERE/uninstall.sh" "$LIB/uninstall.sh"
run install -o root -g root -m 0755 "$PKG/bin/harness-priv" /usr/local/sbin/harness-priv
run install -o root -g root -m 0755 "$PKG/bin/harness-control" /usr/local/bin/harness-control
run install -o root -g root -m 0755 "$PKG/bin/harness-control-mcp" /usr/local/bin/harness-control-mcp

# --- политика: меняется только переустановкой пакета -----------------------------------------
if [[ $MODE != install || ! -e $ETC/harness.json ]]; then
  run install -o root -g root -m 0644 "$HERE/harness.json" "$ETC/harness.json"
fi
while read -r f; do
  case $f in policy.d/*) run install -o root -g root -m 0644 "$PKG/$f" "$ETC/$f" ;; esac
done < <(package_files)

# --- юниты ------------------------------------------------------------------------------------
for u in harness-control-recover.service harness-canary.service harness-canary.timer; do
  run install -o root -g root -m 0644 "$HERE/$u" "$SYSTEMD/$u"
done
for u in $(unit_files); do
  [[ -e $SYSTEMD/$u ]] || run install -o root -g root -m 0644 "$UNITS_SRC/$u" "$SYSTEMD/$u"
done
if [[ ! -e /usr/local/lib/harness-canary/canary.py ]]; then
  run install -d -o root -g root -m 0755 /usr/local/lib/harness-canary
  run install -o root -g root -m 0755 "$PKG/canary/canary.py" /usr/local/lib/harness-canary/canary.py
  run install -o root -g root -m 0644 "$PKG/canary/VERSION" /usr/local/lib/harness-canary/VERSION
fi
run systemctl daemon-reload
run systemctl enable harness-control-recover.service
echo '  (harness-canary.timer ставится выключенным: проверка вручную, расписание включает оператор на время проверки)'
echo '  (multica-provider.timer ставится выключенным: его включает harness-control по --capabilities артефакта)'

# --- baseline: текущие установленные файлы, чтобы откат был с первого дня ---------------------
for c in "${COMPONENTS[@]}"; do
  run /usr/local/sbin/harness-priv adopt-baseline "$c"
done

# --- доступ агента: последним ------------------------------------------------------------------
run install -o root -g root -m 0440 "$HERE/sudoers.harness-control" "$SUDOERS"
if [[ $MODE != check ]]; then
  /usr/sbin/visudo -cf "$SUDOERS" >/dev/null || { rm -f "$SUDOERS"; echo 'sudoers не прошёл visudo -c; доступ агента не выдан' >&2; exit 1; }
  echo 'готово. Проверка от имени agents: harness-control inspect'
  echo "откат установки: sudo $LIB/uninstall.sh [--restore-baseline]"
fi
