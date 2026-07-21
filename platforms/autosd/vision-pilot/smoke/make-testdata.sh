#!/usr/bin/env bash
# Cut the OpenLane sample into deterministic 100-frame and 10-frame pairs.
# Usage: make-testdata.sh <input.mp4> <input_speed_file> <outdir>
#
# Source: OpenLane sample test_open_lane_10 (10 fps, 198 frames; frame_speed.txt
# holds one float per frame, so `head -n N` keeps the clip and speed aligned).
set -euo pipefail
IN_VIDEO="$1"; IN_SPEED="$2"; OUT="$3"; mkdir -p "$OUT"
SPEED_EXT="${IN_SPEED##*.}"
for n in 100 10; do
  ffmpeg -y -i "$IN_VIDEO" -vf "select='lt(n\,$n)'" -vsync 0 -an "$OUT/clip$n.mp4"
  head -n "$n" "$IN_SPEED" > "$OUT/speed$n.$SPEED_EXT"   # frame_speed.txt is one value per frame
done
(cd "$OUT" && sha256sum clip100.mp4 "speed100.$SPEED_EXT" clip10.mp4 "speed10.$SPEED_EXT" | tee SHA256SUMS)
