# Dockerfile - Builds simulator runtime image
ARG COMMON_BASE_IMAGE=ghcr.io/autowarefoundation/openadkit-common:base
ARG COMMON_DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common:devel
ARG ROS_DISTRO=humble

# =============================================================================
# Build stage: simulator-devel
# =============================================================================
FROM $COMMON_DEVEL_IMAGE AS simulator-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install rosdep dependencies and build packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
  --mount=type=bind,source=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_simulator_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_simulator_launch \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/simulator,target=/autoware/src/universe/autoware_universe/simulator \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/perception/autoware_shape_estimation,target=/autoware/src/universe/autoware_universe/perception/autoware_shape_estimation \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/perception/autoware_multi_object_tracker,target=/autoware/src/universe/autoware_universe/perception/autoware_multi_object_tracker \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/perception/autoware_elevation_map_loader,target=/autoware/src/universe/autoware_universe/perception/autoware_elevation_map_loader \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/perception/autoware_detected_object_feature_remover,target=/autoware/src/universe/autoware_universe/perception/autoware_detected_object_feature_remover \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/perception/autoware_tensorrt_common,target=/autoware/src/universe/autoware_universe/perception/autoware_tensorrt_common \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/perception/autoware_probabilistic_occupancy_grid_map,target=/autoware/src/universe/autoware_universe/perception/autoware_probabilistic_occupancy_grid_map \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/perception/autoware_map_based_prediction,target=/autoware/src/universe/autoware_universe/perception/autoware_map_based_prediction \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/sensing/autoware_cuda_utils,target=/autoware/src/universe/autoware_universe/perception/autoware_cuda_utils \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor,target=/autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions,target=/autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/vehicle/autoware_raw_vehicle_cmd_converter,target=/autoware/src/universe/autoware_universe/vehicle/autoware_raw_vehicle_cmd_converter \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-simulator-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-simulator-pkgs.txt \
  && cat /tmp/rosdep-simulator-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && /scripts/build_and_clean.sh "${CCACHE_DIR}" /opt/autoware

# =============================================================================
# Runtime stage: simulator
# =============================================================================
FROM $COMMON_BASE_IMAGE AS simulator
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Copy rosdep dependency lists
COPY --from=simulator-devel /tmp/rosdep-universe-common-exec-pkgs.txt /tmp/rosdep-universe-common-exec-pkgs.txt
COPY --from=simulator-devel /tmp/rosdep-simulator-exec-pkgs.txt /tmp/rosdep-simulator-exec-pkgs.txt

# Set up runtime environment and install rosdep dependencies
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module all --no-nvidia --no-cuda-drivers --runtime openadkit --ros-distro $ROS_DISTRO \
  && pipx uninstall ansible \
  && apt-get update \
  && cat /tmp/rosdep-universe-common-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && cat /tmp/rosdep-simulator-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && /scripts/cleanup_system.sh $ROS_DISTRO

# Copy binaries from devel stage
COPY --from=simulator-devel /opt/autoware /opt/autoware

ENTRYPOINT ["/scripts/autoware_entrypoint.sh"]
CMD ["/bin/bash"]
