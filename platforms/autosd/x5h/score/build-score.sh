#!/usr/bin/env bash
# Build the S-CORE pieces of the X5H demo role and pack them for /usr/local.
#   build-score.sh <outdir> [aarch64|x86_64]   -> <outdir>/score-x5h-<arch>.tar
# x86_64 build host only: the GCC 12 and Ferrocene toolchains declare an
# x86_64 Linux execution host. BAZEL names bazelisk (default: bazelisk).
# Both architectures write to the same bazel-out directory, so this packs the
# tar right after its own build and never reads the other architecture's files.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
[ $# -ge 1 ] || { echo "usage: $0 <outdir> [aarch64|x86_64]" >&2; exit 2; }
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
ARCH=${2:-aarch64}
case "$ARCH" in aarch64|x86_64) ;; *) echo "usage: $0 <outdir> [aarch64|x86_64]" >&2; exit 2 ;; esac
BAZEL=${BAZEL:-bazelisk}
cd "$HERE"
flags=(--lockfile_mode=error "--config=$ARCH-linux")
targets=(
    @score_lifecycle//score/launch_manager:launch_manager
    @score_logging//score/datarouter:datarouter
    //vp:libscore_vp.so
    //vp:vp_standin
)
for c in demo gate sil; do
    [ -f "config/$c/BUILD.bazel" ] && targets+=("//config/$c:lm_config")
done
"$BAZEL" build "${flags[@]}" "${targets[@]}"
bin=$(readlink -f "$HERE/bazel-bin")
stage=$(mktemp -d); trap 'rm -rf "$stage"' EXIT
s="$stage/score"
install -D -m0755 "$bin/external/score_lifecycle+/score/launch_manager/src/daemon/launch_manager" "$s/bin/launch_manager"
install -D -m0755 "$bin/external/score_logging+/score/datarouter/datarouter" "$s/bin/datarouter"
install -D -m0755 "$bin/vp/vp_standin" "$s/bin/vp_standin"
install -D -m0644 "$bin/vp/libscore_vp.so" "$s/lib/libscore_vp.so"
for c in demo gate sil; do
    f="$bin/config/$c/etc/launch_manager_config.bin"
    [ -f "$f" ] && install -D -m0644 "$f" "$s/etc/$c/launch_manager_config.bin"
done
[ -f config/gate/logging.json ] && install -D -m0644 config/gate/logging.json "$s/etc/gate/logging.json"
if [ -d sil ]; then
    install -d "$s/sil"
    cp -a sil/. "$s/sil/"
fi
tar -C "$stage" -cf "$OUT/score-x5h-$ARCH.tar" score
echo "OK: $OUT/score-x5h-$ARCH.tar"
