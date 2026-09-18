#!/usr/bin/env bash
set -u
name=test-vp-npu-gate
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/vp-npu-gate.sh"; fx="$here/fixtures/vp-latency-sample.log"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
exact() { [ "$1" = "$2" ] || fail "$3 out=$1"; }
[ -x "$s" ] || fail script_missing

out=$(bash "$s" --frames 10 --log "$fx") || fail "good_failed $out"
grep -q '^VP_NPU_PASS frames=10 wall_avg_ms=24.4 wall_max_ms=25.0 from_frame=1$' <<<"$out" || fail "pass_line out=$out"

out=$(bash "$s" --frames 11 --log "$fx") && fail too_few_accepted
exact "$out" 'VP_NPU_FAIL reason=too_few n=10' too_few_reason

tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
sed 's/wall=24.8/wall=31.7/' "$fx" > "$tmp"
out=$(bash "$s" --frames 10 --log "$tmp") && fail slow_accepted
exact "$out" 'VP_NPU_FAIL reason=slow frame=6 wall_ms=31.7' slow_reason

# A warm-up spike ahead of a long enough clean window is what the criterion
# calls N consecutive frames under budget, so it passes and from_frame says
# the window began after it. Board 2, 2026-09-18: frame 1 at 30.9 ms, then
# 955 frames at 23 to 25 ms.
sed '0,/wall=/s/wall=[0-9.]*/wall=30.9/' "$fx" > "$tmp"
out=$(bash "$s" --frames 9 --log "$tmp") || fail "warmup_spike_rejected out=$out"
grep -q '^VP_NPU_PASS frames=9 .* from_frame=2$' <<<"$out" || fail "warmup_window out=$out"
# ... but the same spike with no room left to spare is still a failure.
out=$(bash "$s" --frames 10 --log "$tmp") && fail warmup_spike_overcounted
exact "$out" 'VP_NPU_FAIL reason=slow frame=1 wall_ms=30.9' warmup_spike_reason

grep -v 'Offload gate PASSED' "$fx" > "$tmp"
out=$(bash "$s" --frames 10 --log "$tmp") && fail no_offload_accepted
exact "$out" 'VP_NPU_FAIL reason=no_offload' offload_reason

# --max-wall-ms driven as a real flag, in both directions: a tight limit
# must turn a good run into a slow failure, a loose one must still pass.
out=$(bash "$s" --frames 10 --max-wall-ms 20 --log "$fx") && fail max_wall_ms_tight_accepted
exact "$out" 'VP_NPU_FAIL reason=slow frame=1 wall_ms=24.1' max_wall_ms_tight_reason

out=$(bash "$s" --frames 10 --max-wall-ms 50 --log "$fx") || fail max_wall_ms_loose_failed
grep -q '^VP_NPU_PASS ' <<<"$out" || fail "max_wall_ms_loose_reason out=$out"

# Bad args must not disarm the gate: reject non-numeric values and a flag
# with no value at all, instead of silently passing or crashing.
out=$(bash "$s" --frames abc --log "$fx") && fail bad_frames_accepted
exact "$out" 'VP_NPU_FAIL reason=bad_args' bad_frames_reason

out=$(bash "$s" --frames 10 --max-wall-ms abc --log "$fx") && fail bad_max_wall_ms_accepted
exact "$out" 'VP_NPU_FAIL reason=bad_args' bad_max_wall_ms_reason

out=$(bash "$s" --frames) && fail missing_value_accepted
exact "$out" 'VP_NPU_FAIL reason=bad_args' missing_value_reason

# --frames 0 is not a real requirement, and used to divide by zero with no
# marker at all when the log had zero Latency lines. Reject it up front.
out=$(bash "$s" --frames 0 --log "$fx") && fail zero_frames_accepted
exact "$out" 'VP_NPU_FAIL reason=bad_args' zero_frames_reason

echo "TEST_PASS $name"
