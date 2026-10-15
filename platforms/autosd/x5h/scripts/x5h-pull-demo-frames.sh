#!/usr/bin/env bash
# Pull the board half of a demo recording into the run directory.
#   x5h-pull-demo-frames.sh <run-dir>
# Env: X5H_BOARD (default root@192.168.0.20), SSH, X5H_VIDEO_DIR
#      (default /opt/npu/video/hud, the record_dir in vision_pilot.capture.conf)
# Markers: DEMO_FRAMES_PULLED n=<frames> dir=<dir> | DEMO_FRAMES_FAIL reason=<slug>
#
# The bench recorders write the other five streams; this brings back the two
# the board owns, VisionPilot's HUD frames and the journal that places them in
# time. make_demo_reel.py maps HUD frame N to the N-th per-frame Latency line,
# so the two have to describe the same run and the same frames. Every way that
# can quietly stop being true is checked here, at the bench, while the board
# still holds the originals -- not later in the composer, when re-recording
# means another board session.
#
# No time filter takes its bound from the board's clock. The board has no
# RTC, so its wall clock can be wrong by days and a `journalctl --since <date>`
# would select the wrong lines with great confidence. The run is selected by
# its journal stream instead, and the one --since below takes its bound from
# that stream's own first entry, stamped by the same clock.
#
# rsync, not tar over ssh. Board-checked on board 2, 2026-09-18: the AutoSD
# board image ships rsync, cpio, gzip and xz, and ships NO tar, no scp, no
# sftp-server and no python3. A tar pipeline dies there with "tar: command not
# found" and an empty stream, which reads as an empty recording.
set -uo pipefail
BOARD="${X5H_BOARD:-root@192.168.0.20}"
SSH="${SSH:-ssh}"
RSYNC="${RSYNC:-rsync}"
VIDEO_DIR="${X5H_VIDEO_DIR:-/opt/npu/video/hud}"
TAG=x5h-vp
# SD_MESSAGE_JOURNAL_DROPPED: journald's "Suppressed N messages" line.
DROPPED_ID=a596d6fe7bfa4994828e72309e95d61e

fail() { echo "DEMO_FRAMES_FAIL reason=$1${2:+ $2}"; exit 1; }

RUN="${1:-}"
[ -n "$RUN" ] || fail usage
[ -d "$RUN" ] || fail no_run_dir "$RUN"
hud="$RUN/hud"
mkdir -p "$hud" || fail mkdir_failed "$hud"

# The launch manager starts VisionPilot through systemd-cat, so each run is
# one journal stream with its own _PID, and the last stream is the last run.
# VisionPilot no longer restarts on failure, so one run is one stream, and the
# FrameRecorder index starts at zero with it.
pid=$("$SSH" "$BOARD" "journalctl -t $TAG -n 1 -o verbose --no-pager" | sed -n 's/^ *_PID=//p') \
    || fail journal_unreadable
[ -n "$pid" ] || fail no_unit_start
journal=$("$SSH" "$BOARD" "journalctl -t $TAG _PID=$pid -o short-monotonic --no-pager") \
    || fail journal_unreadable
[ -n "$journal" ] || fail journal_empty

# journald's own rate limit drops messages and says so in one line. At up to
# 40 Latency lines a second this is a real risk, and a journal with a hole in
# it looks perfectly well formed. journald logs that line under its own
# identifier, never inside this stream, so ask for it by message id from the
# stream's first entry on.
t0=$("$SSH" "$BOARD" "journalctl -t $TAG _PID=$pid -o short-unix --no-pager -q" | sed -n '1s/[. ].*//p') \
    || fail journal_unreadable
[ -n "$t0" ] || fail journal_empty
drops=$("$SSH" "$BOARD" "journalctl MESSAGE_ID=$DROPPED_ID --since @$t0 -o cat --no-pager -q") \
    || fail journal_unreadable
suppressed=$(grep -c . <<<"$drops" || true)
[ "$suppressed" -eq 0 ] || fail journal_suppressed "$suppressed lines"

printf '%s\n' "$journal" > "$hud/vp-journal.txt" || fail journal_unwritable
frames=$(grep -c "Latency.*wall=" <<<"$journal")
[ "$frames" -gt 0 ] || fail no_hud_frames

"$RSYNC" -a --include='frame_*.png' --exclude='*' \
    "$BOARD:$VIDEO_DIR/" "$hud/" || fail rsync_failed
pngs=$(find "$hud" -name 'frame_*.png' -type f | wc -l)
[ "$pngs" -gt 0 ] || fail no_pngs "$VIDEO_DIR"

# One PNG per rendered frame and one journal line per rendered frame is the
# whole basis of the mapping. A difference means the directory was not emptied
# before the run, or the pull lost files; either way the reel would be built on
# a shifted mapping that nothing downstream can detect.
#
# Exactly one extra PNG is the exception, and it is what the kill route
# produces: the sink writes the frame and VisionPilot is killed before it
# prints that frame's Latency line. Board-measured 2026-09-18, pngs=396
# journal=395. That last frame has no time, so the composer drops it.
[ "$pngs" -eq "$frames" ] || [ "$pngs" -eq "$((frames + 1))" ] \
    || fail frame_count "pngs=$pngs journal=$frames"

echo "DEMO_FRAMES_PULLED n=$pngs dir=$hud"
