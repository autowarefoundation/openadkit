# Dockerfile - Builds universe runtime image
ARG COMMON_BASE_IMAGE=ghcr.io/autowarefoundation/openadkit-common:base
ARG COMMON_DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common:devel
ARG SENSING_PERCEPTION_IMAGE=ghcr.io/autowarefoundation/openadkit:sensing-perception
ARG LOCALIZATION_MAPPING_IMAGE=ghcr.io/autowarefoundation/openadkit:localization-mapping
ARG PLANNING_CONTROL_IMAGE=ghcr.io/autowarefoundation/openadkit:planning-control
ARG VEHICLE_SYSTEM_IMAGE=ghcr.io/autowarefoundation/openadkit:vehicle-system
ARG API_IMAGE=ghcr.io/autowarefoundation/openadkit:api
ARG VISUALIZER_IMAGE=ghcr.io/autowarefoundation/openadkit:visualizer
ARG SIMULATOR_IMAGE=ghcr.io/autowarefoundation/openadkit:simulator

# Import component images for COPY
FROM $SENSING_PERCEPTION_IMAGE AS sensing-perception
FROM $LOCALIZATION_MAPPING_IMAGE AS localization-mapping
FROM $PLANNING_CONTROL_IMAGE AS planning-control
FROM $VEHICLE_SYSTEM_IMAGE AS vehicle-system
FROM $API_IMAGE AS api
FROM $VISUALIZER_IMAGE AS visualizer
FROM $SIMULATOR_IMAGE AS simulator

ARG ROS_DISTRO=humble

# =============================================================================
# Build stage: universe-devel
# =============================================================================
FROM $COMMON_DEVEL_IMAGE AS universe-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install rosdep dependencies and build packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
  --mount=type=bind,source=autoware/src,target=/autoware/src \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-universe-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-universe-pkgs.txt \
  && cat /tmp/rosdep-universe-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true

# =============================================================================
# Runtime stage: universe
# =============================================================================
FROM $COMMON_BASE_IMAGE AS universe
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Copy rosdep dependency lists
COPY --from=universe-devel /tmp/rosdep-universe-exec-pkgs.txt /tmp/rosdep-universe-exec-pkgs.txt

# Set up runtime environment and install rosdep dependencies
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module all --no-nvidia --no-cuda-drivers --runtime openadkit --ros-distro $ROS_DISTRO \
  && pipx uninstall ansible \
  && apt-get update \
  && cat /tmp/rosdep-universe-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && /scripts/cleanup_system.sh $ROS_DISTRO

# Copy binaries from component images
COPY --from=api /opt/autoware /opt/autoware
COPY --from=localization-mapping /opt/autoware /opt/autoware
COPY --from=planning-control /opt/autoware /opt/autoware
COPY --from=vehicle-system /opt/autoware /opt/autoware
COPY --from=api /opt/autoware /opt/autoware
COPY --from=visualizer /opt/autoware /opt/autoware
COPY --from=simulator /opt/autoware /opt/autoware
COPY --from=sensing-perception /opt/autoware /opt/autoware

ENTRYPOINT ["/scripts/autoware_entrypoint.sh"]
CMD ["/bin/bash"]
