#!/usr/bin/env bash
set -euo pipefail

# Runtime images do not need build headers or static libraries from the
# project-owned install trees copied from build stages. Never delete files
# owned by apt/rosdep packages: doing so leaves the package database corrupt.
find /opt/autoware /opt/acados \
    -type f \( -name '*.a' -o -name '*.o' \) -delete 2>/dev/null || true
rm -rf \
    /opt/autoware/include \
    /opt/acados/include \
    /root/.cache \
    /home/aw/.cache
