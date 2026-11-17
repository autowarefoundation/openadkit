#!/usr/bin/env bash
set -euo pipefail

# Point the ROS apt source at a dated snapshot of packages.ros.org.
#
# packages.ros.org only serves the latest ROS sync, while the upstream Autoware
# images ship binaries compiled against the sync they were built from. Using
# that sync's snapshot keeps every stage on the exact ROS versions those
# binaries, and ours, link against. See README.md.
#
# Usage: ros-snapshot.sh <YYYY-MM-DD> [--check [BASE_DPKG_DIR]]
#   --check  fail when an installed ROS package is newer than the snapshot
#            serves, or when one this image installed over the image whose
#            dpkg database is BASE_DPKG_DIR is not the snapshot's version
#
# Upstream images are layered: a base image built from one ROS sync, and core
# installed later from another. The packages core added are what it compiled
# against and must be the snapshot's; the base's may be older.

snapshot="${1:?usage: ros-snapshot.sh <YYYY-MM-DD> [--check [BASE_DPKG_DIR]]}"
check="${2:-}"
base_dpkg="${3:-}"
: "${ROS_DISTRO:?ROS_DISTRO is required}"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null
. /etc/os-release

# Replace the live ROS source: ros2-apt-source links ros2.sources, older images
# carry a .list entry.
{ grep -l 'packages\.ros\.org' /etc/apt/sources.list.d/* 2>/dev/null || true; } | xargs -r rm -f
[ ! -f /etc/apt/sources.list ] || sed -i '/packages\.ros\.org/d' /etc/apt/sources.list
# Key 4B63CF8FDE49746E98FA01DDAD19BAB3CBF125EA (ROS Snapshot builder).
install -m 0644 "${script_dir}/ros-snapshots.asc" /usr/share/keyrings/ros-snapshots.asc
cat > /etc/apt/sources.list.d/ros2-snapshot.sources <<EOF
Types: deb
URIs: http://snapshots.ros.org/${ROS_DISTRO}/${snapshot}/ubuntu
Suites: ${VERSION_CODENAME}
Components: main
Signed-By: /usr/share/keyrings/ros-snapshots.asc
EOF
apt-get update

[ "${check}" = --check ] || exit 0

ros_packages() {
    dpkg-query "$@" -W -f='${db:Status-Abbrev} ${Package}=${Version}\n' "ros-${ROS_DISTRO}-*" |
        awk '$1 == "ii" { print $2 }' | sort
}
mapfile -t installed < <(ros_packages)
[ "${#installed[@]}" -gt 0 ] || { echo "ros snapshot: no ROS packages installed" >&2; exit 1; }
declare -A served=() added=()
while IFS='|' read -r package version _; do
    package=${package// /} version=${version// /}
    [ -n "${served[${package}]:-}" ] || served[${package}]=${version}
done < <(apt-cache madison "${installed[@]%%=*}")
if [ -n "${base_dpkg}" ]; then
    while read -r entry; do
        added[${entry}]=1
    done < <(comm -23 <(printf '%s\n' "${installed[@]}") <(ros_packages --admindir="${base_dpkg}"))
fi

mismatched=()
for entry in "${installed[@]}"; do
    version=${entry#*=} want=${served[${entry%%=*}]:-}
    if [ -z "${want}" ] || dpkg --compare-versions "${version}" gt "${want}" \
        || { [ -n "${added[${entry}]:-}" ] && [ "${version}" != "${want}" ]; }; then
        mismatched+=("${entry} (snapshot: ${want:-none})")
    fi
done
if [ "${#mismatched[@]}" -gt 0 ]; then
    echo "ros snapshot ${snapshot} does not match this image's ROS packages:" >&2
    printf '%s\n' "${mismatched[@]}" | head -20 | sed 's/^/  /' >&2
    echo "Set the ROS snapshot the upstream image was built from (components/docker-bake.hcl)." >&2
    exit 1
fi
echo "ros snapshot ${snapshot}: ${#installed[@]} installed ROS packages match${base_dpkg:+ (${#added[@]} added over the base)}"
