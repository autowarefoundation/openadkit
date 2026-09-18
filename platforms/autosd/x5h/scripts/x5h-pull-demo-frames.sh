#!/usr/bin/env bash
# Pull the board half of a demo recording into the run directory.
#   x5h-pull-demo-frames.sh <run-dir>
# Env: X5H_BOARD (default root@192.168.0.20), SSH, X5H_VIDEO_DIR
#      (default /opt/npu/video/hud, the record_dir in vision_pilot.capture.conf)
# Markers: DEMO_FRAMES_PULLED n=<frames> dir=<dir> | DEMO_FRAMES_FAIL reason=<slug>
#
# The bench recorders write the other four streams; this brings back the two
# the board owns, VisionPilot's HUD frames and the journal that places them in
# time. make_demo_reel.py maps HUD frame N to the N-th per-frame Latency line,
# so the two have to describe the same run and the same frames. Every way that
# can quietly stop being true is checked here, at the bench, while the board
# still holds the originals -- not later in the composer, when re-recording
# means another board session.
#
# No time filter is used anywhere. The board has no RTC and no NTP on the
# bench LAN, so its wall clock is wrong by days and `journalctl --since` would
# select the wrong lines with great confidence. The journal is sliced at the
# last unit start instead, which is a position in the file rather than a time.
#
# tar over ssh rather than rsync: the AutoSD board image ships no rsync.
set -uo pipefail
BOARD="${X5H_BOARD:-root@192.168.0.20}"
SSH="${SSH:-ssh}"
VIDEO_DIR="${X5H_VIDEO_DIR:-/opt/npu/video/hud}"
UNIT=x5h-vp

fail() { echo "DEMO_FRAMES_FAIL reason=$1${2:+ $2}"; exit 1; }

RUN="${1:-}"
[ -n "$RUN" ] || fail usage
[ -d "$RUN" ] || fail no_run_dir "$RUN"
hud="$RUN/hud"
mkdir -p "$hud" || fail mkdir_failed "$hud"

journal=$("$SSH" "$BOARD" "journalctl -u $UNIT -o short-monotonic --no-pager") \
    || fail journal_unreadable
[ -n "$journal" ] || fail journal_empty

# Slice at the LAST unit start. VisionPilot restarts on failure, and the
# FrameRecorder index restarts at zero with it, so a journal spanning two runs
# describes more frames than the directory holds and every frame after the
# first restart would be placed at the wrong instant.
sliced=$(awk '/Started .*'"$UNIT"'/ { n = NR } END { print n + 0 }' <<<"$journal")
[ "$sliced" -gt 0 ] || fail no_unit_start
journal=$(awk -v from="$sliced" 'NR >= from' <<<"$journal")

# journald's own rate limit drops messages and says so in one line. At up to
# 40 Latency lines a second this is a real risk, and a journal with a hole in
# it looks perfectly well formed.
suppressed=$(grep -c "uppressed" <<<"$journal")
[ "$suppressed" -eq 0 ] || fail journal_suppressed "$suppressed lines"

printf '%s\n' "$journal" > "$hud/vp-journal.txt" || fail journal_unwritable
frames=$(grep -c "Latency.*wall=" <<<"$journal")
[ "$frames" -gt 0 ] || fail no_hud_frames

"$SSH" "$BOARD" "tar -C $(dirname "$VIDEO_DIR") -cf - $(basename "$VIDEO_DIR")" \
    | tar -C "$hud" --strip-components=1 -xf - || fail tar_failed
pngs=$(find "$hud" -name 'frame_*.png' -type f | wc -l)
[ "$pngs" -gt 0 ] || fail no_pngs "$VIDEO_DIR"

# One PNG per rendered frame and one journal line per rendered frame is the
# whole basis of the mapping. A difference means the directory was not emptied
# before the run, or the pull lost files; either way the reel would be built on
# a shifted mapping that nothing downstream can detect.
[ "$pngs" -eq "$frames" ] || fail frame_count "pngs=$pngs journal=$frames"

echo "DEMO_FRAMES_PULLED n=$pngs dir=$hud"
