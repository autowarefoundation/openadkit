#!/usr/bin/env bash
# Download + verify pinned smoke test data. Usage: fetch-testdata.sh <destdir> <100|10>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/testdata.env"
DEST="$1"; N="$2"; mkdir -p "$DEST"
for f in "clip$N.mp4" "speed$N.$SPEED_EXT"; do
  curl -fsSL -o "$DEST/$f" "$TESTDATA_BASE/$f"
done
sha_var_clip="CLIP${N}_SHA256"; sha_var_speed="SPEED${N}_SHA256"
echo "${!sha_var_clip}  $DEST/clip$N.mp4" | sha256sum -c -
echo "${!sha_var_speed}  $DEST/speed$N.$SPEED_EXT" | sha256sum -c -
