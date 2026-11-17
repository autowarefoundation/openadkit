#!/usr/bin/env bash
set -euo pipefail

# Runtime images do not need build headers or static libraries from the
# project-owned install trees copied from build stages. Never delete files
# owned by apt/rosdep packages: doing so leaves the package database corrupt.
find /opt/autoware /opt/acados \
    -type f \( -name '*.a' -o -name '*.o' \) -delete 2>/dev/null || true
# The upstream base keeps pipx's shared pip after uninstalling ansible
# (~/.local/pipx on Humble, ~/.local/share/pipx on Jazzy); a runtime image
# installs nothing with pipx, and that pip vendors an outdated certifi.
rm -rf \
    /opt/autoware/include \
    /opt/autoware/*/include \
    /root/.cache \
    /home/aw/.cache \
    /home/aw/.local/pipx \
    /home/aw/.local/share/pipx
