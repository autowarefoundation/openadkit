#!/usr/bin/env bash
# Checks an S-CORE tar from build-score.sh. Needs SCORE_TAR (an aarch64 tar)
# because a fresh checkout has no build; run.sh skips it without one.
# The checks are the facts the board depends on: aarch64 ELF, no libstdc++ or
# libatomic at run time, exactly the four C symbols, the LM's remote log
# backend, and every configuration.
set -u
name=test-score-artifacts
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -n "${SCORE_TAR:-}" ] || fail SCORE_TAR_unset
[ -f "$SCORE_TAR" ] || fail no_tar
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
tar -xf "$SCORE_TAR" -C "$tmp" || fail untar
s="$tmp/score"
for f in bin/launch_manager bin/datarouter bin/vp_standin lib/libscore_vp.so \
         etc/demo/launch_manager_config.bin etc/gate/launch_manager_config.bin \
         etc/sil/launch_manager_config.bin etc/recording/launch_manager_config.bin \
         etc/gate/logging.json; do
    [ -s "$s/$f" ] || fail "missing_$f"
done
for f in bin/launch_manager bin/datarouter lib/libscore_vp.so; do
    case "$(file -b "$s/$f")" in *"ARM aarch64"*) ;; *) fail "not_aarch64_$f" ;; esac
    needed=$(readelf -d "$s/$f" | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p')
    case "$needed" in *libstdc++*|*libatomic*) fail "dynamic_runtime_dep_$f" ;; esac
done
syms=$(nm -D --defined-only "$s/lib/libscore_vp.so" | awk '$2 == "T" { print $3 }' | sort | tr '\n' ' ')
[ "$syms" = "score_vp_frame_begin score_vp_frame_end score_vp_init score_vp_report_running " ] \
    || fail "exports=$syms"
# lm-logging.json asks for kRemote. Without the remote backend in the link the
# LM falls back to the console, and its half of SG5 never reaches the bench.
nm -C "$s/bin/launch_manager" | grep -F 'CreateRemoteRecorder' > /dev/null \
    || fail lm_no_remote_backend
echo "TEST_PASS $name"
