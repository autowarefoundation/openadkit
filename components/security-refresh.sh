#!/usr/bin/env bash
set -euo pipefail

# Refresh the security packages that a pinned upstream base image may lag on.
#
# The Dockerfiles call this as their last build step: the build passes a
# per-build SECURITY_REFRESH argument, so only the calling layer re-runs and
# the expensive layers above it (rosdep, acados, colcon) stay cached while
# the image still picks up the latest security updates.
mapfile -t security_packages < <(
    dpkg-query -W -f='${binary:Package}\n' 2>/dev/null |
        grep -E '^(libssl-dev|libssl3|libssl3t64|linux-libc-dev|openssl|rsync)(:.*)?$' ||
        true
)

apt-get update
if [ "${#security_packages[@]}" -gt 0 ]; then
    DEBIAN_FRONTEND=noninteractive \
        apt-get install -y --only-upgrade --no-install-recommends "${security_packages[@]}"
fi