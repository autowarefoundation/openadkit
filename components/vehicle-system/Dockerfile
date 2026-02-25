# Dockerfile - Builds vehicle-system runtime image
ARG COMMON_BASE_IMAGE=ghcr.io/autowarefoundation/openadkit-common:base
ARG COMMON_DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common:devel
ARG ROS_DISTRO=humble

# =============================================================================
# Build stage: vehicle-system-devel
# =============================================================================
FROM $COMMON_DEVEL_IMAGE AS vehicle-system-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install rosdep dependencies and build packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
  --mount=type=bind,source=autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_vehicle_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_vehicle_launch \
  --mount=type=bind,source=autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_system_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_system_launch \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/vehicle,target=/autoware/src/universe/autoware_universe/vehicle \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/system,target=/autoware/src/universe/autoware_universe/system \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/localization/autoware_pose2twist,target=/autoware/src/universe/autoware_universe/localization/autoware_pose2twist \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/planning/planning_validator,target=/autoware/src/universe/autoware_universe/planning/planning_validator \
  --mount=type=bind,source=autoware/src/sensor_component/external/sensor_component_description,target=/autoware/src/sensor_component/external/sensor_component_description \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-vehicle-system-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-vehicle-system-pkgs.txt \
  && cat /tmp/rosdep-vehicle-system-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && /scripts/build_and_clean.sh "${CCACHE_DIR}" /opt/autoware

# =============================================================================
# Runtime stage: vehicle-system
# =============================================================================
FROM $COMMON_BASE_IMAGE AS vehicle-system
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Copy rosdep dependency lists
COPY --from=vehicle-system-devel /tmp/rosdep-universe-common-exec-pkgs.txt /tmp/rosdep-universe-common-exec-pkgs.txt
COPY --from=vehicle-system-devel /tmp/rosdep-vehicle-system-exec-pkgs.txt /tmp/rosdep-vehicle-system-exec-pkgs.txt

# Set up runtime environment and install rosdep dependencies
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module all --no-nvidia --no-cuda-drivers --runtime openadkit --ros-distro $ROS_DISTRO \
  && pipx uninstall ansible \
  && apt-get update \
  && cat /tmp/rosdep-universe-common-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && cat /tmp/rosdep-vehicle-system-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && /scripts/cleanup_system.sh $ROS_DISTRO

# Copy binaries from devel stage
COPY --from=vehicle-system-devel /opt/autoware /opt/autoware

ENTRYPOINT ["/scripts/autoware_entrypoint.sh"]
CMD ["/bin/bash"]
