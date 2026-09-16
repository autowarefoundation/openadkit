#!/usr/bin/env bash
set -u
name=test-vp-npu-gate
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/vp-npu-gate.sh"; fx="$here/fixtures/vp-latency-sample.log"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
exact() { [ "$1" = "$2" ] || fail "$3 out=$1"; }
[ -x "$s" ] || fail script_missing

out=$(bash "$s" --frames 10 --log "$fx") || fail "good_failed $out"
grep -q '^VP_NPU_PASS frames=10 wall_avg_ms=24.4 wall_max_ms=25.0$' <<<"$out" || fail "pass_line out=$out"

out=$(bash "$s" --frames 11 --log "$fx") && fail too_few_accepted
exact "$out" 'VP_NPU_FAIL reason=too_few n=10' too_few_reason

tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
sed 's/wall=24.8/wall=31.7/' "$fx" > "$tmp"
out=$(bash "$s" --frames 10 --log "$tmp") && fail slow_accepted
exact "$out" 'VP_NPU_FAIL reason=slow frame=6 wall_ms=31.7' slow_reason

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

echo "TEST_PASS $name"
