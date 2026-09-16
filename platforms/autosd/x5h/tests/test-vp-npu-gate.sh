#!/usr/bin/env bash
set -u
name=test-vp-npu-gate
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/vp-npu-gate.sh"; fx="$here/fixtures/vp-latency-sample.log"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
out=$(bash "$s" --frames 10 --log "$fx") || fail "good_failed $out"
grep -q '^VP_NPU_PASS frames=10 wall_avg_ms=24.4 wall_max_ms=25.0$' <<<"$out" || fail "pass_line out=$out"
out=$(bash "$s" --frames 11 --log "$fx") && fail too_few_accepted
grep -q '^VP_NPU_FAIL reason=too_few n=10$' <<<"$out" || fail too_few_reason
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
sed 's/wall=24.8/wall=31.7/' "$fx" > "$tmp"
out=$(bash "$s" --frames 10 --log "$tmp") && fail slow_accepted
grep -q '^VP_NPU_FAIL reason=slow frame=6 wall_ms=31.7$' <<<"$out" || fail "slow_reason out=$out"
grep -v 'Offload gate PASSED' "$fx" > "$tmp"
out=$(bash "$s" --frames 10 --log "$tmp") && fail no_offload_accepted
grep -q '^VP_NPU_FAIL reason=no_offload$' <<<"$out" || fail offload_reason
echo "TEST_PASS $name"
