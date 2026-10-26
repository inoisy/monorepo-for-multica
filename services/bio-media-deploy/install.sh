#!/usr/bin/env bash
# Root-only oneshot, installed at merge. Candidate and guard are staged by the
# operator, never executed directly from the writable bio-course working tree.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Root required' >&2; exit 1; }
exec 9>/run/lock/bio-media-deploy.lock
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }
candidate=/var/lib/bio-media-deploy/candidate
guard=/usr/local/lib/bio-media-deploy/broker_guard.py
target=/usr/local/bin/bio-media-api
backup=/var/lib/bio-media-deploy/previous

# Require an immutable operator-owned snapshot all the way to the filesystem
# root; reject a symlink or a group/world-writable parent before importing it.
python3 -I - "$candidate" "$guard" <<'PY'
import stat
import sys
from pathlib import Path
for item in sys.argv[1:]:
    p = Path(item)
    for part in (p, *p.parents):
        s = part.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            sys.exit('Snapshot/guard must be root-owned, without writable parents or symlinks')
    if not p.is_file():
        sys.exit('Missing candidate or guard')
PY

# Guard executes the candidate without access to the root API key.
runuser -u agents -- /usr/bin/python3 -I "$guard" "$candidate"
install -d -o root -g root -m 0755 /var/lib/bio-media-deploy
if cmp -s "$candidate" "$target"; then
  "$target" --check
  echo 'Already installed; health ok'
  exit 0
fi
[[ -f $target && ! -L $target ]] || { echo 'Expected an existing regular broker for rollback' >&2; exit 1; }
install -o root -g root -m 0700 "$target" "$backup.new"
mv -f "$backup.new" "$backup"
install -o root -g root -m 0755 "$candidate" "$target.new"
mv -f "$target.new" "$target"
if ! "$target" --check; then
  install -o root -g root -m 0755 "$backup" "$target.new"
  mv -f "$target.new" "$target"
  "$target" --check
  echo 'Health failed; previous broker restored' >&2
  exit 1
fi
echo 'Broker installed; health ok; no paid requests'
