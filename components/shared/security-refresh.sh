#!/usr/bin/env bash
set -euo pipefail

# Upgrade every installed package that Ubuntu's own archive has an update for.
#
# Only the Ubuntu sources are read, so nothing else can move: ROS installs from
# a pinned snapshot (ros-snapshot/), and the NVIDIA CUDA/TensorRT repository
# would change the ABI the compiled tree links against. Ubuntu updates keep the
# ABI of a release, which check-linked-libs.sh verifies after this step.
#
# The Dockerfiles call this as a final build step with a per-build
# SECURITY_REFRESH argument, so only this layer re-runs on each build.
sources=$(mktemp -d)
lists=$(mktemp -d)
trap 'rm -rf "${sources}" "${lists}"' EXIT
# Jammy lists Ubuntu in sources.list; Noble in sources.list.d/ubuntu.sources.
[ ! -f /etc/apt/sources.list.d/ubuntu.sources ] || cp /etc/apt/sources.list.d/ubuntu.sources "${sources}/"
mkdir -p "${lists}/partial"
# apt downloads as _apt; give these the permissions of apt's own directories.
chmod 755 "${sources}" "${lists}"
chown _apt "${lists}/partial"
apt_ubuntu=(
    -o Dir::Etc::SourceList=/etc/apt/sources.list
    -o "Dir::Etc::SourceParts=${sources}"
    -o "Dir::State::Lists=${lists}"
)

# Error-Mode=any: by default update exits 0 when it cannot reach the archive,
# and the upgrade below then finds nothing: the image would ship without the
# refresh, and nothing would say so.
apt-get "${apt_ubuntu[@]}" -o APT::Update::Error-Mode=any update
DEBIAN_FRONTEND=noninteractive apt-get "${apt_ubuntu[@]}" upgrade -y \
    --with-new-pkgs --no-install-recommends \
    -o Dpkg::Options::=--force-confold
