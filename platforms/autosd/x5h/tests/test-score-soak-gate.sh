#!/usr/bin/env bash
# score-soak-gate.sh with fake journalctl, chronyc and sleep.
set -u
name=test-score-soak-gate
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/score-soak-gate.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/journalctl" <<'EOT'
#!/bin/sh
case "$*" in
  *--show-cursor*) echo '-- cursor: s=abc' ;;
  *score-lm*) cat "$LMLOG" ;;
  *x5h-vp*) cat "$VPLOG" ;;
esac
EOT
cat > "$tmp/chronyc" <<'EOT'
#!/bin/sh
echo "Leap status     : ${LEAP:-Normal}"
echo "System time     : ${OFFSET:-0.000200} seconds fast of NTP time"
EOT
cat > "$tmp/systemctl" <<'EOT'
#!/bin/sh
[ -z "${LM_DOWN:-}" ]
EOT
chmod +x "$tmp/journalctl" "$tmp/chronyc" "$tmp/systemctl"
: > "$tmp/lm"
for i in $(seq 1 6000); do echo '[INFO]  frame_ms=40.0'; done > "$tmp/vp"
for i in 1 2 3; do echo '[INFO]  frame_ms=50.0'; done >> "$tmp/vp"
run() { LMLOG="$tmp/lm" VPLOG="$1" JOURNALCTL="$tmp/journalctl" CHRONYC="$tmp/chronyc" SYSTEMCTL="$tmp/systemctl" SLEEP=true bash "$s" --minutes "${MINUTES:-10}" --max-frame-ms 80; }
out=$(run "$tmp/vp") || fail "good_failed $out"
# Three slow frames in 6003 sit above the 99.9th percentile.
[ "$out" = 'SCORE_SOAK_PASS frames=6003 p999_ms=40.0 over=0 longest_over=0 offset_ms=0.2' ] || fail "pass_line out=$out"
echo 'Alive Supervision ( visionpilot ) switched to FAILED' > "$tmp/lm"
out=$(run "$tmp/vp") && fail fallback_accepted
[ "$out" = 'SCORE_SOAK_FAIL reason=alive_failed' ] || fail "alive_line out=$out"
: > "$tmp/lm"
head -n 100 "$tmp/vp" > "$tmp/vp-short"
out=$(run "$tmp/vp-short") && fail short_accepted
[ "$out" = 'SCORE_SOAK_FAIL reason=too_few_frames frames=100' ] || fail "short_line out=$out"
for i in $(seq 1 10); do echo '[INFO]  frame_ms=70.0'; done >> "$tmp/vp"
out=$(run "$tmp/vp") && fail margin_accepted
case "$out" in 'SCORE_SOAK_FAIL reason=deadline_margin p999_ms=70.0'*) ;; *) fail "margin_line out=$out" ;; esac
out=$(OFFSET=0.020000 run "$tmp/vp") && fail offset_accepted
[ "$out" = 'SCORE_SOAK_FAIL reason=clock_offset offset_ms=20.0' ] || fail "offset_line out=$out"
out=$(LEAP='Not synchronised' run "$tmp/vp") && fail unsynced_accepted
[ "$out" = 'SCORE_SOAK_FAIL reason=clock_unsynced' ] || fail "unsynced_line out=$out"
out=$(MINUTES=0 run "$tmp/vp") && fail zero_minutes_accepted
[ "$out" = 'SCORE_SOAK_FAIL reason=usage' ] || fail "zero_minutes_line out=$out"
out=$(LM_DOWN=1 run "$tmp/vp") && fail lm_down_accepted
[ "$out" = 'SCORE_SOAK_FAIL reason=lm_inactive' ] || fail "lm_down_line out=$out"
echo "TEST_PASS $name"
