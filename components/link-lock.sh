#!/usr/bin/env bash
set -euo pipefail

# Compile-time ROS dependency lock.
#
# `generate` runs in a devel stage after colcon and records the ROS packages
# our compiled libraries link against, with the exact versions they were
# linked against. `verify` runs in the matching runtime stage and fails the
# build if any version differs, which would be an ABI mismatch waiting to
# happen (see 07-testler.md: diagnostic_updater 4.2.6 vs 4.2.7).
#
# Usage: link-lock.sh generate [output]
#        link-lock.sh verify [input]

action="${1:?usage: link-lock.sh generate|verify [file]}"
file="${2:-/opt/openadkit/link-lock.txt}"

generate() {
    mkdir -p "$(dirname "${file}")"
    declare -A needed=() packages=()

    while IFS= read -r lib; do
        while IFS= read -r name; do
            [ -n "${name}" ] || continue
            needed["${name}"]=1
        done < <(readelf -d "${lib}" 2>/dev/null | awk -F'[][]' '/NEEDED/ {print $2}')
    done < <(find /opt/autoware -type f \( -name '*.so' -o -name '*.so.*' \))

    for name in "${!needed[@]}"; do
        path="/opt/ros/${ROS_DISTRO}/lib/${name}"
        [ -e "${path}" ] || continue
        pkg=$(dpkg -S "$(readlink -f "${path}")" 2>/dev/null | cut -d: -f1 || true)
        [ -n "${pkg}" ] && packages["${pkg}"]=1
    done

    for pkg in "${!packages[@]}"; do
        dpkg-query -W -f='${Package}=${Version}\n' "${pkg}"
    done | sort > "${file}"
    echo "link lock: ${#packages[@]} packages -> ${file}"
}

verify() {
    [ -f "${file}" ] || { echo "link lock missing: ${file}" >&2; exit 1; }
    drift=0
    while IFS='=' read -r pkg expected; do
        [ -n "${pkg}" ] || continue
        installed=$(dpkg-query -W -f='${Version}' "${pkg}" 2>/dev/null || true)
        if [ "${installed}" != "${expected}" ]; then
            echo "drift: ${pkg}: compiled=${expected} runtime=${installed:-missing}" >&2
            drift=1
        fi
    done < "${file}"
    if [ "${drift}" -ne 0 ]; then
        echo "runtime ROS packages do not match the compile lock; rerun the runtime install step or rebuild" >&2
        exit 1
    fi
    echo "link lock OK: $(wc -l < "${file}") packages match"
}

case "${action}" in
    generate) generate ;;
    verify) verify ;;
    *)
        echo "unknown action '${action}'" >&2
        exit 2
        ;;
esac