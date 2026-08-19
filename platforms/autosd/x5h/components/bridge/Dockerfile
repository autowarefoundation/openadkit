# syntax=docker/dockerfile:1
# domain_bridge for the X5H single-ECU topology: joins DDS domain 1 (the
# Open AD Kit component containers on the application cluster) to domain 2
# (the CR52 actuation module over the rpmsg-eth link).
#
# Provenance: the conventional domain_bridge container recipe -- install
# ros-${ROS_DISTRO}-domain-bridge on a ROS 2 Humble base, then run
# `ros2 run domain_bridge domain_bridge` over a YAML topic map -- applied to
# this project's base image. Everything project-specific is in this
# directory: the six-topic map in bridge-config.yaml and entrypoint.sh. Both
# are readable on their own terms and neither depends on an external tree,
# so this image can be rebuilt from what is committed here.
#
# Based on an Open AD Kit component image rather than
# ghcr.io/autowarefoundation/autoware:universe, which is the base the plain
# domain_bridge recipe would reach for. The board stages planning-control
# anyway, so building on it costs one thin layer instead of a second
# multi-gigabyte base on the board's ~19 GB container-store partition
# (/dev/sdc3, inside a 32 GB UFS LUN -- see scripts/stage-container-images.sh,
# which gates on the measured free space of that partition).
#
# The default below is the amd64 build (tag
# planning-control-amd64-humble-32105383688-1) for host rehearsal: upstream's
# bare tag (ghcr.io/autowarefoundation/openadkit:planning-control) publishes
# no arm64 manifest at all and its amd64 build dates from 2026-02-25, so we
# pin our fork's per-arch build by digest instead.
# A ref cannot carry both a tag and a digest (containers-image rejects it),
# so the tag the digest below was read from is recorded here instead of in
# the ref itself.
#
# The arm64 board build overrides BASE_IMAGE with the digest recorded for
# openadkit-planning-control in ../images.txt. Nothing else in this repo
# produces localhost/openadkit-bridge:latest -- images.txt cannot stage it,
# because it has no registry ref -- so the whole recipe is here:
#
#   # 1. build for the board's architecture. On an amd64 host this needs
#   #    qemu-user-static + binfmt registered, and the apt-get layer above
#   #    then runs under emulation (slow, but it is one thin layer).
#   podman build --platform linux/arm64 \
#     --build-arg BASE_IMAGE=ghcr.io/youtalk/openadkit@sha256:b9044abf68e829ad31b5052a0ea9552bcc29d5a956bc3f73c6edff4d8d932080 \
#     -t localhost/openadkit-bridge:latest \
#     platforms/autosd/x5h/components/bridge
#
#   # 2. transfer it onto the board, streamed rather than staged to disk --
#   #    the same shape stage-container-images.sh uses for the six
#   #    registry-sourced images, and for the same reason: the board's
#   #    /var/tmp is not sized for a second full copy.
#   podman save localhost/openadkit-bridge:latest \
#     | ssh -o BatchMode=yes root@192.168.0.20 "podman load"
#
# The BASE_IMAGE digest in step 1 is openadkit-planning-control's arm64
# digest from ../images.txt; re-read it from that file rather than copying
# it from here, so the bridge and the component it builds on can never
# drift apart. BRIDGE_IMAGE in ../awf-oak-x5h.env is the tag step 1 sets.
ARG BASE_IMAGE=ghcr.io/youtalk/openadkit@sha256:f8fb6ad96df6a90232b25f5f3c65961272ab03bc066ecdfed44b0348a029c6c2
FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO=humble
WORKDIR /autoware

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ros-${ROS_DISTRO}-domain-bridge \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Deliberately staying root here, not switching to a non-root user: the
# base image's own final stage does `USER root` and never switches back
# (confirmed via `docker history` -- its runtime stage copies build
# artifacts and runs further apt/rosdep steps as root with no later `USER`
# instruction), and every sibling openadkit-* component image in this stack
# (images.txt) inherits that same root default. Switching only this image
# to non-root would make the bridge the one odd container in the stack
# rather than making anything more consistent. A uid-1000 "aw" account
# does already exist in the base (USERNAME=aw in its ENV, build artifacts
# chowned aw:aw) if the whole stack is ever moved off root -- that would be
# a fix to the base image, not to this Dockerfile alone. Please do not
# re-add a per-image USER switch here without doing that stack-wide.

ENTRYPOINT ["/entrypoint.sh"]
