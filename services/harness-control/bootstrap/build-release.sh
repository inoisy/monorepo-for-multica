#!/usr/bin/env bash
# Собирает пакет оператора из коммита: harness-control-<версия>.tar.gz + SHA256SUMS.
#   build-release.sh [rev] [каталог-вывода]    rev по умолчанию HEAD, вывод — ./dist
# Сборка детерминирована: одинаковый коммит даёт тот же SHA256. Тесты в пакет не входят.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
REV=${1:-HEAD}
OUT=${2:-$PWD/dist}
SERVICE=$(realpath --relative-to="$REPO" "$(dirname -- "$HERE")")
CONVEYOR=$(dirname -- "$SERVICE")/multica-conveyor
COMMIT=$(git -C "$REPO" rev-parse --verify "$REV^{commit}")
STAMP=$(git -C "$REPO" show -s --format=%ct "$COMMIT")
VERSION=$(git -C "$REPO" show "$COMMIT:$SERVICE/VERSION")
NAME=harness-control-$VERSION-${COMMIT:0:12}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/$NAME/units"
git -C "$REPO" archive "$COMMIT:$SERVICE" | tar -x -C "$WORK/$NAME"
rm -rf "$WORK/$NAME/tests" "$WORK/$NAME/dist"
find "$WORK/$NAME" -name __pycache__ -prune -exec rm -rf {} +
for u in multica-provider.service multica-provider.timer; do
  git -C "$REPO" show "$COMMIT:$CONVEYOR/systemd/$u" > "$WORK/$NAME/units/$u"
done
(cd "$WORK/$NAME" && find . -type f ! -name MANIFEST.sha256 | LC_ALL=C sort | sed 's|^\./||' | xargs sha256sum > MANIFEST.sha256)
mkdir -p "$OUT"
tar --sort=name --mtime="@$STAMP" --owner=0 --group=0 --numeric-owner -C "$WORK" -cf - "$NAME" | gzip -n > "$OUT/$NAME.tar.gz"
(cd "$OUT" && sha256sum "$NAME.tar.gz" > SHA256SUMS)
echo "пакет: $OUT/$NAME.tar.gz"
cat "$OUT/SHA256SUMS"
echo "установка (root): tar -xzf $NAME.tar.gz && sudo bash $NAME/bootstrap/install.sh"
