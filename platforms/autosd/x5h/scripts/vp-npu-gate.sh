#!/usr/bin/env bash
# Gate D5: VisionPilot runs on the NPU under 30 ms end to end for N frames.
#   vp-npu-gate.sh [--frames 396] [--max-wall-ms 30] [--log <file>]
# Reads podman logs x5h-vp unless --log names a file. Requires the merged
# backend's "Offload gate PASSED" line (a run that completes on the CPU
# fallback is not a pass) and N consecutive Latency lines under the limit.
set -uo pipefail
bad_args() { echo "VP_NPU_FAIL reason=bad_args"; exit 1; }
FRAMES=396; MAX=30; LOG=""
while [ $# -gt 0 ]; do case "$1" in
  --frames)
    [ $# -ge 2 ] || bad_args
    [[ $2 =~ ^[0-9]+$ ]] || bad_args
    FRAMES=$2; shift 2 ;;
  --max-wall-ms)
    [ $# -ge 2 ] || bad_args
    [[ $2 =~ ^[0-9]+([.][0-9]+)?$ ]] || bad_args
    MAX=$2; shift 2 ;;
  --log)
    [ $# -ge 2 ] || bad_args
    LOG=$2; shift 2 ;;
  *) bad_args ;; esac; done
if [ -n "$LOG" ]; then text=$(cat "$LOG"); else text=$(podman logs x5h-vp 2>&1); fi
grep -q 'Offload gate PASSED' <<<"$text" || { echo "VP_NPU_FAIL reason=no_offload"; exit 1; }
awk -v want="$FRAMES" -v max="$MAX" '
  /Latency .*wall=/ {
    match($0, /wall=[0-9.]+/); w = substr($0, RSTART + 5, RLENGTH - 5) + 0
    n++; if (w > max) { printf "VP_NPU_FAIL reason=slow frame=%d wall_ms=%.1f\n", n, w; bad=1; exit 1 }
    sum += w; if (w > mx) mx = w
  }
  END {
    if (bad) exit 1
    if (n < want) { printf "VP_NPU_FAIL reason=too_few n=%d\n", n; exit 1 }
    printf "VP_NPU_PASS frames=%d wall_avg_ms=%.1f wall_max_ms=%.1f\n", n, sum / n, mx
  }' <<<"$text"
