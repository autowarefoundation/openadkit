#!/usr/bin/env bash
set -euo pipefail

# Runtime images do not need build headers or static libraries from copied
# install trees. System files are removed only after apt/rosdep has finished.
mode="${1:-final}"
find /opt/ros /opt/autoware /opt/acados \
    -type f \( -name '*.a' -o -name '*.o' \) -delete 2>/dev/null || true
rm -rf \
    "/opt/ros/${ROS_DISTRO}/include" \
    /opt/autoware/include \
    /opt/acados/include \
    /root/.cache \
    /home/aw/.cache

if [ "$mode" = "final" ]; then
    find /usr/lib -type f \( -name '*.a' -o -name '*.o' \) -delete 2>/dev/null || true
    rm -rf /usr/include/* /usr/lib/gcc /usr/lib/jvm /usr/lib/llvm*
    find /usr/share/doc /usr/share/man -mindepth 1 -type f -delete 2>/dev/null || true
fi
