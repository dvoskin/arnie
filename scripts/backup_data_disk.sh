#!/usr/bin/env bash
# Back up the /data disk's per-user memory (B9/B10 — the store Postgres backups
# miss). Run in the Render service shell where /data is mounted, then copy the
# printed artifact off-box (object storage). Read-only w.r.t. /data: it only reads
# and writes a tarball to $OUT_DIR.
#
#   DATA_DIR=/data/users OUT_DIR=/tmp scripts/backup_data_disk.sh
#
# To restore-verify: untar into a scratch dir and confirm a sample
#   <id>/arnie_memory.md and profile.md are present and non-empty.
set -euo pipefail

DATA_DIR="${DATA_DIR:-/data/users}"
OUT_DIR="${OUT_DIR:-/tmp}"

if [ ! -d "$DATA_DIR" ]; then
  echo "ERROR: DATA_DIR '$DATA_DIR' not found — run this where /data is mounted." >&2
  exit 1
fi

# No Date.now() games — the caller stamps the name so reruns don't collide.
STAMP="${BACKUP_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
ART="$OUT_DIR/arnie-data-users-$STAMP.tar.gz"

FILE_COUNT="$(find "$DATA_DIR" -type f | wc -l | tr -d ' ')"
echo "Backing up $DATA_DIR ($FILE_COUNT files) -> $ART"
tar -czf "$ART" -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")"

# Integrity: sha256 the artifact so the off-box copy can be verified later.
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ART" | tee "$ART.sha256"
else
  shasum -a 256 "$ART" | tee "$ART.sha256"   # macOS
fi

BYTES="$(wc -c < "$ART" | tr -d ' ')"
echo "DONE: $ART ($BYTES bytes, $FILE_COUNT files)"
echo "Next: copy '$ART' and '$ART.sha256' off-box (object storage)."
