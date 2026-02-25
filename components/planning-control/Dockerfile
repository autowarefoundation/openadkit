# Dockerfile - Builds planning-control runtime image
ARG COMMON_BASE_IMAGE=ghcr.io/autowarefoundation/openadkit-common:base
ARG COMMON_DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common:devel
ARG ROS_DISTRO=humble

# =============================================================================
# Build stage: planning-control-devel
# =============================================================================
FROM $COMMON_DEVEL_IMAGE AS planning-control-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install rosdep dependencies and build packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
  --mount=type=bind,source=autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_control_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_control_launch \
  --mount=type=bind,source=autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_planning_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_planning_launch \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/control,target=/autoware/src/universe/autoware_universe/control \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/planning,target=/autoware/src/universe/autoware_universe/planning \
  # TODO(youtalk): Remove mounts when https://github.com/autowarefoundation/autoware_universe/issues/8805 is resolved
  --mount=type=bind,source=autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions,target=/autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor,target=/autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/sensing/autoware_cuda_utils,target=/autoware/src/universe/autoware_universe/sensing/autoware_cuda_utils \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/perception/autoware_tensorrt_common,target=/autoware/src/universe/autoware_universe/perception/autoware_tensorrt_common \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/perception/autoware_tensorrt_plugins,target=/autoware/src/universe/autoware_universe/perception/autoware_tensorrt_plugins \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/vehicle/autoware_external_cmd_converter,target=/autoware/src/universe/autoware_universe/vehicle/autoware_external_cmd_converter \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/vehicle/autoware_raw_vehicle_cmd_converter,target=/autoware/src/universe/autoware_universe/vehicle/autoware_raw_vehicle_cmd_converter \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/system/autoware_command_mode_types,target=/autoware/src/universe/autoware_universe/system/autoware_command_mode_types \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-planning-control-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-planning-control-pkgs.txt \
  && cat /tmp/rosdep-planning-control-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && /scripts/build_and_clean.sh "${CCACHE_DIR}" /opt/autoware

# =============================================================================
# Runtime stage: planning-control
# =============================================================================
FROM $COMMON_BASE_IMAGE AS planning-control
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Copy rosdep dependency lists
COPY --from=planning-control-devel /tmp/rosdep-universe-common-exec-pkgs.txt /tmp/rosdep-universe-common-exec-pkgs.txt
COPY --from=planning-control-devel /tmp/rosdep-planning-control-exec-pkgs.txt /tmp/rosdep-planning-control-exec-pkgs.txt

# Set up runtime environment and install rosdep dependencies
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module all --no-nvidia --no-cuda-drivers --runtime openadkit --ros-distro $ROS_DISTRO \
  && pipx uninstall ansible \
  && apt-get update \
  && cat /tmp/rosdep-universe-common-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && cat /tmp/rosdep-planning-control-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && /scripts/cleanup_system.sh $ROS_DISTRO

# Copy binaries from devel stage
COPY --from=planning-control-devel /opt/autoware /opt/autoware

ENTRYPOINT ["/scripts/autoware_entrypoint.sh"]
CMD ["/bin/bash"]
