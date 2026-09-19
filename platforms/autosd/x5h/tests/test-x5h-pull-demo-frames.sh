#!/usr/bin/env bash
# x5h-pull-demo-frames.sh against a fake ssh: it slices the journal at the last
# unit start, refuses a rate-limited journal, refuses a PNG count that does not
# match the journal's frame count, and reports the count it pulled.
#
# The fake ssh answers two commands, journalctl and tar, from files this test
# writes, which is the whole board contract the script depends on.
set -u
name=test-x5h-pull-demo-frames
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/x5h-pull-demo-frames.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/ssh" <<'EOF'
#!/bin/sh
# $1 is the board, $2 the remote command.
case "$2" in
  journalctl*) cat "$JOURNAL" ;;
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
make_journal() {  # make_journal <starts> <frames-after-last-start>
    : > "$tmp/journal"
    for _ in $(seq 1 "$1"); do
        echo "[    100.000000] board systemd[1]: Started x5h-vp.service - VisionPilot." >> "$tmp/journal"
        for i in $(seq 1 "$2"); do
            echo "[    $((100 + i)).000000] $latency" >> "$tmp/journal"
        done
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
    JOURNAL="$tmp/journal" PNGDIR="$tmp/board" SSH="$tmp/ssh" RSYNC="$tmp/rsync" X5H_BOARD=fake \
        bash "$s" "$tmp/run"
}

# A clean run: one start, five frames, five PNGs.
make_journal 1 5; make_pngs 5
out=$(run) || fail "clean_run_failed out=$out"
[ "$out" = "DEMO_FRAMES_PULLED n=5 dir=$tmp/run/hud" ] || fail "marker out=$out"
[ -f "$tmp/run/hud/vp-journal.txt" ] || fail no_journal_written
[ -f "$tmp/run/hud/frame_000003.png" ] || fail no_pngs_pulled

# Two starts: only the frames after the last one count, and the PNG directory
# holds that many, because the sink's index restarted with the process.
make_journal 2 5; make_pngs 5
out=$(run) || fail "restart_run_failed out=$out"
[ "$out" = "DEMO_FRAMES_PULLED n=5 dir=$tmp/run/hud" ] || fail "restart_marker out=$out"
n=$(grep -c 'Started ' "$tmp/run/hud/vp-journal.txt")
[ "$n" -eq 1 ] || fail "journal_not_sliced starts=$n"

# A journal that never shows the unit starting cannot be sliced at all.
make_journal 1 5; make_pngs 5
grep -v 'Started ' "$tmp/journal" > "$tmp/j2"; mv "$tmp/j2" "$tmp/journal"
out=$(run) && fail no_start_accepted
[ "$out" = "DEMO_FRAMES_FAIL reason=no_unit_start" ] || fail "no_start_reason out=$out"

# journald dropped messages: the mapping has a hole in it.
make_journal 1 5; make_pngs 5
echo "[    110.000000] board systemd-journald[9]: Suppressed 214 messages" >> "$tmp/journal"
out=$(run) && fail suppressed_accepted
case "$out" in DEMO_FRAMES_FAIL\ reason=journal_suppressed*) ;; *) fail "suppressed_reason out=$out" ;; esac

# More PNGs than the journal describes: a directory that was not emptied.
make_journal 1 5; make_pngs 9
out=$(run) && fail count_mismatch_accepted
case "$out" in DEMO_FRAMES_FAIL\ reason=frame_count*) ;; *) fail "count_reason out=$out" ;; esac

# No run directory at all.
out=$(JOURNAL="$tmp/journal" PNGDIR="$tmp/board" SSH="$tmp/ssh" RSYNC="$tmp/rsync" X5H_BOARD=fake \
    bash "$s" "$tmp/nope") && fail missing_dir_accepted
case "$out" in DEMO_FRAMES_FAIL\ reason=no_run_dir*) ;; *) fail "dir_reason out=$out" ;; esac

echo "TEST_PASS $name"
