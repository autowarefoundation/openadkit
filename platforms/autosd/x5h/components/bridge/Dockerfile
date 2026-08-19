# syntax=docker/dockerfile:1
# domain_bridge for the X5H single-ECU topology: joins DDS domain 1 (the
# Autoware stack on the application cluster) to domain 2 (the CR52
# actuation module over the rpmsg-eth link).
#
# Provenance: the conventional domain_bridge container recipe -- install
# ros-${ROS_DISTRO}-domain-bridge on a ROS 2 Humble base, then run
# `ros2 run domain_bridge domain_bridge` over a YAML topic map -- applied to
# this project's base image. Everything project-specific is in this
# directory: the six-topic map in bridge-config.yaml and entrypoint.sh. Both
# are readable on their own terms and neither depends on an external tree,
# so this image can be rebuilt from what is committed here.
#
# Based on the Autoware image this profile already runs
# (AUTOWARE_IMAGE in ../awf-oak-x5h.env), not on
# ghcr.io/autowarefoundation/autoware:universe, which is the base the plain
# domain_bridge recipe would reach for. Two reasons, both measured:
#
#   1. domain_bridge is in NEITHER image this milestone stages. `ros2 pkg
#      prefix domain_bridge` reports "Package not found" in universe-after,
#      and there is no share/domain_bridge in universe-after or in
#      scenario-simulator. So a bridge image is genuinely required; it is
#      not a leftover from the retired component stack.
#   2. The board's container store (/dev/sdc3, ~19 GB, inside a 32 GB UFS
#      LUN) has about 6.3 GB free with the two monolithic images loaded --
#      LESS headroom than the six componentized images left, not more.
#      There is no room for a second multi-gigabyte base. Layering on the
#      resident universe-after costs only the ros-humble-domain-bridge
#      layer.
#
# This replaced a base of ghcr.io/youtalk/openadkit@sha256:b9044abf... (the
# openadkit-planning-control component image), which has been deleted from
# the board along with the rest of the componentized set. The old rationale
# -- "the board stages planning-control anyway" -- no longer holds; the
# reasoning is the same shape, applied to the image the board now holds.
#
# BASE_IMAGE IS A TAG, NOT A DIGEST, and that is deliberate. The registry
# digest for this image is
# sha256:d161659c110c0a27522468a3e5318bed11bfab75a763f8c01075da6916ea18b2,
# but the copy on the board does NOT carry it: it was loaded from an OCI
# archive, and `skopeo copy` to oci-archive rewrites the Docker schema-2
# manifest to OCI media types, which changes both the config blob and the
# manifest digest. A digest reference would therefore miss in the local
# store and send podman to ghcr.io for a 5.02 GB pull. Content identity of
# the loaded image was verified a different way, by matching all 27
# rootfs.diff_ids against the registry.
#
# Build ON THE BOARD, where the base already is:
#
#   # 1. copy this directory across (it is three small files)
#   scp -r platforms/autosd/x5h/components/bridge \
#     root@192.168.0.20:/var/tmp/openadkit-bridge
#
#   # 2. build the thin layer. --pull=never keeps podman off the network
#   #    for the BASE; the apt-get inside the build still needs the board
#   #    to be able to reach the ROS 2 apt repositories, and --network=host
#   #    is what lets it. THAT FLAG IS REQUIRED, not a preference: podman's
#   #    default bridge network (10.88.0.0/16) has no working egress on this
#   #    board -- the nat table carries no masquerade rule for it, so every
#   #    connection out of a build container times out, DNS included, and
#   #    apt reports "Temporary failure resolving 'packages.ros.org'" after
#   #    minutes of silence. Measured 2026-08-19: the same curl that returns
#   #    200 in ~0.2 s under --network=host times out entirely under the
#   #    default network. --network=host is a per-build flag; it changes no
#   #    board configuration.
#   ssh root@192.168.0.20 \
#     'podman build --pull=never --network=host \
#        -t localhost/openadkit-bridge:latest \
#        /var/tmp/openadkit-bridge && rm -rf /var/tmp/openadkit-bridge'
#
# Building on an amd64 host and streaming the result across (the shape the
# previous recipe used, and what stage-container-images.sh does for
# registry images) still works, but it costs a multi-gigabyte
# `podman save | ssh podman load` for a layer of a few tens of megabytes,
# because the saved archive carries the whole base. Prefer the board build.
#
# BRIDGE_IMAGE in ../awf-oak-x5h.env is the tag step 2 sets. Nothing else in
# this repo produces it -- images.txt cannot stage it, because it has no
# registry ref -- so the whole recipe is here.
ARG BASE_IMAGE=ghcr.io/mitsudome-r/mrm-demo:universe-after-arm64
FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO=humble
WORKDIR /autoware

USER root
# -o Acquire::Check-Date=false: THE BOARD HAS NO CLOCK, and that is a
# standing property of it rather than a transient skew. Its RTC reads year
# 2000 (dead cell -- `hwclock -r` times out on it) and neither
# systemd-timesyncd nor chronyd is installed, so `timedatectl` reports
# "System clock synchronized: no" with "NTP service: n/a" and systemd falls
# back to its build epoch: the board comes up at 2026-07-31 every boot and
# then sits there while real time moves on. Measured 2026-08-19, 19 days
# adrift, apt refused EVERY repository -- "Release file ... is not valid yet
# (invalid for another 18d 13h 46min)" for ports.ubuntu.com and 7d 8h for
# packages.ros.org -- and the build died with exit status 100.
#
# The flag relaxes only the Date / Valid-Until freshness check. The InRelease
# GPG signature is still verified, so a build here installs the same package
# bytes a correctly-clocked build would. The alternative remedy is to set the
# clock by hand before every build, which a dead RTC makes a per-boot chore
# rather than a fix.
RUN apt-get -o Acquire::Check-Date=false update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ros-${ROS_DISTRO}-domain-bridge \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Deliberately staying root here, not switching to a non-root user: the
# base image declares no USER at all (`podman image inspect` reports an
# empty User, i.e. root), and so its entrypoint and every other unit in
# this stack run as root. Switching only this image to non-root would make
# the bridge the one odd container in the stack rather than making
# anything more consistent -- and /ros_entrypoint.sh in the base has its
# own uid-remap path (LOCAL_UID / LOCAL_USER / LOCAL_GID / LOCAL_GROUP,
# gosu) that our entrypoint replaces, so a USER line here would interact
# with a mechanism that is no longer in the picture. Moving off root is a
# stack-wide change, not a per-image one. Please do not re-add a per-image
# USER switch here without doing it stack-wide.

ENTRYPOINT ["/entrypoint.sh"]
