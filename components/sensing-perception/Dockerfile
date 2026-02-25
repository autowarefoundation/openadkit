# Dockerfile - Builds sensing-perception runtime image
ARG COMMON_BASE_IMAGE=ghcr.io/autowarefoundation/openadkit-common:base
ARG COMMON_DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common:devel
ARG ROS_DISTRO=humble

# =============================================================================
# Build stage: sensing-perception-devel
# =============================================================================
FROM $COMMON_DEVEL_IMAGE AS sensing-perception-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install rosdep dependencies and build packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
--mount=type=bind,source=autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_perception_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_perception_launch \
--mount=type=bind,source=autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_sensing_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_sensing_launch \
--mount=type=bind,source=autoware/src/universe/external/trt_batched_nms,target=/autoware/src/universe/external/trt_batched_nms \
--mount=type=bind,source=autoware/src/universe/external/bevdet_vendor,target=/autoware/src/universe/external/bevdet_vendor \
--mount=type=bind,source=autoware/src/universe/external/cuda_blackboard,target=/autoware/src/universe/external/cuda_blackboard \
--mount=type=bind,source=autoware/src/universe/external/negotiated,target=/autoware/src/universe/external/negotiated \
--mount=type=bind,source=autoware/src/universe/autoware_universe/perception,target=/autoware/src/universe/autoware_universe/perception \
--mount=type=bind,source=autoware/src/universe/autoware_universe/sensing,target=/autoware/src/universe/autoware_universe/sensing \
--mount=type=bind,source=autoware/src/sensor_component,target=/autoware/src/sensor_component \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-sensing-perception-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-sensing-perception-pkgs.txt \
  && cat /tmp/rosdep-sensing-perception-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && /scripts/build_and_clean.sh "${CCACHE_DIR}" /opt/autoware

# =============================================================================
# Runtime stage: sensing-perception
# =============================================================================
FROM $COMMON_BASE_IMAGE AS sensing-perception
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Copy rosdep dependency lists
COPY --from=sensing-perception-devel /tmp/rosdep-universe-common-exec-pkgs.txt /tmp/rosdep-universe-common-exec-pkgs.txt
COPY --from=sensing-perception-devel /tmp/rosdep-sensing-perception-exec-pkgs.txt /tmp/rosdep-sensing-perception-exec-pkgs.txt

# Set up runtime environment and install rosdep dependencies
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module all --no-nvidia --no-cuda-drivers --runtime openadkit --ros-distro $ROS_DISTRO \
  && pipx uninstall ansible \
  && apt-get update \
  && cat /tmp/rosdep-universe-common-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && cat /tmp/rosdep-sensing-perception-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && /scripts/cleanup_system.sh $ROS_DISTRO

# Copy binaries from devel stage
COPY --from=sensing-perception-devel /opt/autoware /opt/autoware

ENTRYPOINT ["/scripts/autoware_entrypoint.sh"]
CMD ["/bin/bash"]
