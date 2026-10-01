#!/usr/bin/env bash
# The exec scripts the S-CORE launch manager starts: each one removes the
# stale ready file BEFORE podman starts, exec's (so the PID the launch manager
# watches is podman's), and carries the container boundary. The board script
# and the SIL script must carry the same boundary, or the SIL proves a
# boundary the board does not have.
set -u
name=test-x5h-score-exec
here=$(cd "$(dirname "$0")" && pwd)
board="$here/../scripts/x5h-score-vp.sh"; sil="$here/../score/sil/sil-vp.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
for s in "$board" "$sil" "$here/../scripts/x5h-score-camera.sh" "$here/../score/sil/sil-camera.sh"; do
    [ -f "$s" ] || fail "missing_$(basename "$s")"
done
boundary='--rm --replace --network=host --cgroups=split --log-driver=passthrough'
vp_boundary="$boundary --ipc=host -v /tmp:/tmp -e IDENTIFIER -e LCM_ALIVE_INTERFACE_PATH -e SCORE_VP_FRAME_MAX_MS -e SCORE_VP_READY_FILE"
for s in "$board" "$sil"; do
    for tok in $vp_boundary; do
        grep -q -- "$tok" "$s" || fail "$(basename "$s")_missing_$tok"
    done
done
for s in "$here/../scripts/x5h-score-camera.sh" "$here/../score/sil/sil-camera.sh"; do
    for tok in $boundary; do
        grep -q -- "$tok" "$s" || fail "$(basename "$s")_missing_$tok"
    done
done
# Run the board VisionPilot script with fake systemd-cat and podman.
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/run"
printf '#!/bin/sh\nshift 2\nexec "$@"\n' > "$tmp/bin/systemd-cat"
cat > "$tmp/bin/podman" <<'EOT'
#!/bin/sh
echo $$ > "$PIDFILE"
[ -e "$SCORE_VP_READY_FILE" ] && echo stale > "$STALEFILE"
exit 0
EOT
chmod +x "$tmp/bin/systemd-cat" "$tmp/bin/podman"
touch "$tmp/run/vp.ready"
sed -e "s#/usr/bin/systemd-cat#$tmp/bin/systemd-cat#; s#/usr/bin/podman#$tmp/bin/podman#; s#mkdir -p /run/score#mkdir -p $tmp/run#" \
    "$board" > "$tmp/vp.sh"
PIDFILE="$tmp/pid" STALEFILE="$tmp/stale" SCORE_VP_READY_FILE="$tmp/run/vp.ready" sh "$tmp/vp.sh" &
spid=$!
wait "$spid" || fail script_failed
[ -e "$tmp/stale" ] && fail ready_file_not_removed_before_podman
[ "$(cat "$tmp/pid")" = "$spid" ] || fail podman_not_execd
echo "TEST_PASS $name"
