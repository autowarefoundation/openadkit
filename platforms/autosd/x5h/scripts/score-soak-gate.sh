#!/usr/bin/env bash
# Gate SG2, on the board: the demo role drives under the S-CORE launch
# manager for N minutes with no fallback, the board clock is within 10 ms of
# rog-amd, and the VisionPilot frame time leaves the frame deadline a 1.5x
# margin at the 99.9th percentile.
#   score-soak-gate.sh [--minutes 10] [--max-frame-ms 80]
# Markers: SCORE_SOAK_PASS frames=<n> p999_ms=<x> over=<n> longest_over=<n> offset_ms=<x>
#        | SCORE_SOAK_FAIL reason=<usage|alive_failed|fallback|lm_inactive|too_few_frames|
#          clock_unsynced|clock_offset|deadline_margin|...>
# The journal is read after a cursor taken at the start: a position, not a
# time, so a clock that is still wrong cannot select the wrong lines.
set -uo pipefail
JOURNALCTL=${JOURNALCTL:-journalctl}; CHRONYC=${CHRONYC:-chronyc}; SLEEP=${SLEEP:-sleep}
SYSTEMCTL=${SYSTEMCTL:-systemctl}
MIN=10; MAX=80
fail() { echo "SCORE_SOAK_FAIL reason=$1${2:+ $2}"; exit 1; }
while [ $# -gt 0 ]; do case "$1" in
    --minutes) [[ ${2:-} =~ ^[0-9]+$ ]] || fail usage; MIN=$2; shift 2 ;;
    --max-frame-ms) [[ ${2:-} =~ ^[0-9]+$ ]] || fail usage; MAX=$2; shift 2 ;;
    *) fail usage ;; esac; done
[ "$MIN" -gt 0 ] && [ "$MAX" -gt 0 ] || fail usage
cursor=$("$JOURNALCTL" -n 0 --show-cursor --no-pager | sed -n 's/^-- cursor: //p')
[ -n "$cursor" ] || fail no_cursor
"$SLEEP" $((MIN * 60))
lm=$("$JOURNALCTL" -u score-lm --after-cursor="$cursor" -o cat --no-pager) || fail journal_unreadable
grep -q 'switched to FAILED' <<<"$lm" && fail alive_failed
# A fallback transition that fails logs only 'activating recovery state'.
grep -q -e 'State fallback' -e 'activating recovery state' <<<"$lm" && fail fallback
# A hard crash logs neither line above, so the unit must still be running.
"$SYSTEMCTL" is-active --quiet score-lm.service || fail lm_inactive
vp=$("$JOURNALCTL" -t x5h-vp --after-cursor="$cursor" -o cat --no-pager) || fail journal_unreadable
vals=$(sed -n 's/.*frame_ms=\([0-9.]*\).*/\1/p' <<<"$vp")
n=$(grep -c . <<<"$vals" || true)
want=$((MIN * 60 * 10 * 9 / 10))
[ "$n" -ge "$want" ] || fail too_few_frames "frames=$n"
p999=$(sort -n <<<"$vals" | awk -v k="$(( (n * 999 + 999) / 1000 ))" 'NR == k')
read -r over longest < <(awk -v max="$MAX" '{ if ($1 > max) { o++; r++; if (r > l) l = r } else r = 0 } END { print o + 0, l + 0 }' <<<"$vals")
track=$("$CHRONYC" tracking)
# An unsynchronised chronyd reports an offset of 0, which would pass.
grep -q '^Leap status *: Normal' <<<"$track" || fail clock_unsynced
off=$(sed -n 's/^System time *: \([0-9.]*\) seconds.*/\1/p' <<<"$track")
[ -n "$off" ] || fail no_chrony
off_ms=$(awk -v s="$off" 'BEGIN { printf "%.1f", s * 1000 }')
awk -v m="$off_ms" 'BEGIN { exit !(m < 10) }' || fail clock_offset "offset_ms=$off_ms"
awk -v p="$p999" -v max="$MAX" 'BEGIN { exit !(p * 1.5 <= max) }' \
    || fail deadline_margin "p999_ms=$p999 max_frame_ms=$MAX"
echo "SCORE_SOAK_PASS frames=$n p999_ms=$p999 over=$over longest_over=$longest offset_ms=$off_ms"
