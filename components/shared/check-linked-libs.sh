#!/usr/bin/env bash
set -euo pipefail

# Fail the build when a compiled Autoware binary cannot load in this image: a
# shared library no installed package provides, or, for an executable, a symbol
# none of its libraries define. The rosdep exec dependencies should install
# everything the tree links against; this proves it at build time, also for the
# images CI evidence cannot run (GPU, CARLA). Libraries get plain ldd, because
# some resolve symbols from the process that loads them.

: "${ROS_DISTRO:?ROS_DISTRO is required}"
# ROS setup scripts reference unset variables.
set +u
# shellcheck source=/dev/null
. "/opt/ros/${ROS_DISTRO}/setup.bash"
# shellcheck source=/dev/null
. /opt/autoware/setup.bash
set -u

checked=0
problems=$(mktemp)
trap 'rm -f "${problems}"' EXIT
while IFS= read -r -d '' file; do
    [ "$(head -c 4 "${file}")" = $'\x7fELF' ] || continue
    checked=$((checked + 1))
    case "${file}" in
        *.so | *.so.*) output=$(ldd "${file}" 2>&1 || true) ;;
        *) output=$(ldd -r "${file}" 2>&1 || true) ;;
    esac
    grep -E 'not found|^undefined symbol' <<<"${output}" | sed "s|^[[:space:]]*|${file}: |" >>"${problems}" || true
done < <(find /opt/autoware -type f \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \) -print0)

if [ -s "${problems}" ]; then
    echo "linked libraries: $(wc -l <"${problems}") unresolved in ${checked} binaries" >&2
    head -40 "${problems}" >&2
    exit 1
fi
echo "linked libraries OK: ${checked} binaries"
