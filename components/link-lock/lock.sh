#!/usr/bin/env bash
set -euo pipefail

# Compile-time ROS dependency lock.
#
# The lock is the set of ROS packages the compiled tree links against, with the
# exact versions it was linked against. Devel stages record it and align the
# tree to the current apt candidates (rebuilding when anything moved); runtime
# stages install those exact versions and verify them, so the runtime cannot
# drift from the compile environment (diagnostic_updater 4.2.6 vs 4.2.7 broke
# Jazzy that way). See README.md.
#
# Usage: lock.sh record [file]
#        lock.sh verify [file]
#        lock.sh upgrade --lock <file>
#        lock.sh install --lock <file>

default_lock=/opt/openadkit/link-lock.txt
action="${1:?usage: lock.sh record|verify|upgrade|install [--lock file]}"
shift

lock="${default_lock}"
case "${1:-}" in
    --lock) lock="${2:?--lock needs a file}" ;;
    "") ;;
    *) lock="$1" ;;
esac

linked_packages() {
    # Every ELF object the compiled tree ships: shared libraries and node
    # executables (an executable-only link would otherwise escape the lock).
    while IFS= read -r name; do
        [ -n "${name}" ] || continue
        path="/opt/ros/${ROS_DISTRO}/lib/${name}"
        [ -e "${path}" ] || continue
        dpkg -S "$(readlink -f "${path}")" 2>/dev/null | cut -d: -f1 || true
    done < <(
        find /opt/autoware -type f \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \) \
            -exec readelf -d {} + 2>/dev/null |
            awk -F'[][]' '/NEEDED/ { print $2 }' | sort -u
    )
}

record() {
    mkdir -p "$(dirname "${lock}")"
    declare -A packages=()
    while IFS= read -r pkg; do
        [ -n "${pkg}" ] || continue
        packages["${pkg}"]=1
    done < <(linked_packages)
    if [ "${#packages[@]}" -eq 0 ]; then
        echo "link lock: no linked ROS packages found under /opt/autoware; check ROS_DISTRO and the image layout" >&2
        exit 1
    fi
    for pkg in "${!packages[@]}"; do
        dpkg-query -W -f='${Package}=${Version}\n' "${pkg}"
    done | sort > "${lock}"
    echo "link lock: ${#packages[@]} packages -> ${lock}"
}

verify() {
    [ -f "${lock}" ] || { echo "link lock missing: ${lock}" >&2; exit 1; }
    drift=0
    while IFS='=' read -r pkg expected; do
        [ -n "${pkg}" ] || continue
        installed=$(dpkg-query -W -f='${Version}' "${pkg}" 2>/dev/null || true)
        if [ "${installed}" != "${expected}" ]; then
            echo "drift: ${pkg}: compiled=${expected} runtime=${installed:-missing}" >&2
            drift=1
        fi
    done < "${lock}"
    if [ "${drift}" -ne 0 ]; then
        echo "runtime ROS packages do not match the compile lock; rerun the runtime install step or rebuild" >&2
        exit 1
    fi
    echo "link lock OK: $(wc -l < "${lock}") packages match"
}

apt_action() {
    [ -f "${lock}" ] || { echo "lock file not found: ${lock}" >&2; exit 1; }
    entries=()
    while IFS= read -r line; do
        line="${line%%#*}"
        line="$(printf '%s' "${line}" | xargs)"
        [ -n "${line}" ] || continue
        entries+=("${line}")
    done < "${lock}"
    [ "${#entries[@]}" -gt 0 ] || return 0
    apt-get update
    case "${action}" in
        upgrade)
            upgrades=()
            for entry in "${entries[@]}"; do
                upgrades+=("${entry%%=*}")
            done
            echo "link lock: upgrading ${#upgrades[@]} linked packages"
            DEBIAN_FRONTEND=noninteractive \
                apt-get install -y --no-install-recommends "${upgrades[@]}"
            ;;
        install)
            echo "link lock: installing ${#entries[@]} locked packages"
            DEBIAN_FRONTEND=noninteractive \
                apt-get install -y --no-install-recommends --allow-downgrades "${entries[@]}"
            ;;
    esac
}

case "${action}" in
    record) record ;;
    verify) verify ;;
    upgrade|install) apt_action ;;
    *)
        echo "unknown action '${action}'" >&2
        exit 2
        ;;
esac