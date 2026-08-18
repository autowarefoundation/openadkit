# syntax=docker/dockerfile:1
# domain_bridge for the X5H single-ECU topology: joins DDS domain 1 (the
# Open AD Kit component containers on the application cluster) to domain 2
# (the CR52 actuation module over the rpmsg-eth link).
#
# Based on an Open AD Kit component image rather than
# ghcr.io/autowarefoundation/autoware:universe (which is what
# autoware-safety-island's demo/bridge/Dockerfile uses). The board stages
# planning-control anyway, so building on it costs one thin layer instead
# of a second multi-gigabyte base on a 32 GB container store.
#
# The default below is the amd64 build (tag
# planning-control-amd64-humble-32105383688-1) for host rehearsal: upstream's
# bare tag (ghcr.io/autowarefoundation/openadkit:planning-control) publishes
# no arm64 manifest at all and its amd64 build dates from 2026-02-25, so we
# pin our fork's per-arch build by digest instead. The arm64 board build
# overrides BASE_IMAGE with the digest recorded for openadkit-planning-control
# in platforms/autosd/x5h/components/images.txt (a later task does this).
# A ref cannot carry both a tag and a digest (containers-image rejects it),
# so the tag the digest below was read from is recorded here instead of in
# the ref itself.
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
