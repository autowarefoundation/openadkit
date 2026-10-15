#!/usr/bin/env bash
# x5h-pull-demo-frames.sh against a fake ssh: it reads the last x5h-vp journal
# stream by its _PID, refuses a run during which journald dropped messages,
# refuses a PNG count that does not match the journal's frame count, and
# reports the count it pulled.
#
# The fake ssh answers the four journalctl queries the script makes, and the
# fake rsync copies PNGs: that is the whole board contract it depends on.
set -u
name=test-x5h-pull-demo-frames
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/x5h-pull-demo-frames.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/ssh" <<'EOF'
#!/bin/sh
# $1 is the board, $2 the remote command.
echo "$2" >> "$CMDS"
case "$2" in
  *'-o verbose'*) [ -n "${NO_STREAM:-}" ] || echo "    _PID=4242" ;;
  *MESSAGE_ID=*) cat "$DROPPED" ;;
  *'_PID=4242 -o short-unix'*) echo "1790000000.250000 board x5h-vp[4242]: first line" ;;
  *'_PID=4242 -o short-monotonic'*) cat "$JOURNAL" ;;
  *) exit 1 ;;
esac
EOF
# The board ships rsync and no tar, so the pull is an rsync and the fake is a
# local copy. $1 and $2 are the rsync flags, $3 the remote source, $4 the
# destination.
cat > "$tmp/rsync" <<'EOF'
#!/bin/sh
eval dst=\${$#}
cp "$PNGDIR"/hud/*.png "$dst" 2>/dev/null
exit 0
EOF
chmod +x "$tmp/ssh" "$tmp/rsync"

latency='board podman[1]: [VP] Latency  pre=1.8 ms  wall=23.6 ms  42 fps'
make_journal() {  # make_journal <frames>: one stream, one run
    : > "$tmp/journal"; : > "$tmp/dropped"
    for i in $(seq 1 "$1"); do
        echo "[    $((100 + i)).000000] $latency" >> "$tmp/journal"
    done
}
make_pngs() {  # make_pngs <n>
    rm -rf "${tmp:?}/board"; mkdir -p "$tmp/board/hud"
    for i in $(seq 1 "$1"); do
        printf 'png' > "$tmp/board/hud/frame_$(printf '%06d' "$i").png"
    done
}
run() {
    rm -rf "${tmp:?}/run"; mkdir -p "$tmp/run"
    : > "$tmp/cmds"
    CMDS="$tmp/cmds" DROPPED="$tmp/dropped" JOURNAL="$tmp/journal" PNGDIR="$tmp/board" \
        SSH="$tmp/ssh" RSYNC="$tmp/rsync" X5H_BOARD=fake bash "$s" "$tmp/run"
}

# A clean run: one stream, five frames, five PNGs.
make_journal 5; make_pngs 5
out=$(run) || fail "clean_run_failed out=$out"
[ "$out" = "DEMO_FRAMES_PULLED n=5 dir=$tmp/run/hud" ] || fail "marker out=$out"
[ -f "$tmp/run/hud/vp-journal.txt" ] || fail no_journal_written
[ -f "$tmp/run/hud/frame_000003.png" ] || fail no_pngs_pulled

# The run is the last stream: the frames come from its _PID, and the drop
# check starts at that stream's first entry, never at the board's own clock.
grep -qx 'journalctl -t x5h-vp _PID=4242 -o short-monotonic --no-pager' "$tmp/cmds" || fail "no_stream_query cmds=$(cat "$tmp/cmds")"
grep -q 'MESSAGE_ID=a596d6fe7bfa4994828e72309e95d61e --since @1790000000 ' "$tmp/cmds" || fail "no_drop_query cmds=$(cat "$tmp/cmds")"

# No x5h-vp stream at all: nothing to pull.
make_journal 5; make_pngs 5
out=$(NO_STREAM=1 run) && fail no_stream_accepted
[ "$out" = "DEMO_FRAMES_FAIL reason=no_unit_start" ] || fail "no_stream_reason out=$out"

# journald dropped messages during the run: the mapping has a hole in it.
make_journal 5; make_pngs 5
echo "score-lm.service: Suppressed 214 messages from score-lm.service" > "$tmp/dropped"
out=$(run) && fail suppressed_accepted
case "$out" in DEMO_FRAMES_FAIL\ reason=journal_suppressed*) ;; *) fail "suppressed_reason out=$out" ;; esac

# More PNGs than the journal describes: a directory that was not emptied.
make_journal 5; make_pngs 9
out=$(run) && fail count_mismatch_accepted
case "$out" in DEMO_FRAMES_FAIL\ reason=frame_count*) ;; *) fail "count_reason out=$out" ;; esac

# No run directory at all.
out=$(CMDS="$tmp/cmds" DROPPED="$tmp/dropped" JOURNAL="$tmp/journal" PNGDIR="$tmp/board" \
    SSH="$tmp/ssh" RSYNC="$tmp/rsync" X5H_BOARD=fake bash "$s" "$tmp/nope") && fail missing_dir_accepted
case "$out" in DEMO_FRAMES_FAIL\ reason=no_run_dir*) ;; *) fail "dir_reason out=$out" ;; esac

echo "TEST_PASS $name"
