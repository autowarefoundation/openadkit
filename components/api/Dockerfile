# Dockerfile - Builds api runtime image
ARG COMMON_BASE_IMAGE=ghcr.io/autowarefoundation/openadkit-common:base
ARG COMMON_DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common:devel
ARG ROS_DISTRO=humble

# =============================================================================
# Build stage: api-devel
# =============================================================================
FROM $COMMON_DEVEL_IMAGE AS api-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install rosdep dependencies and build packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
  --mount=type=bind,source=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_autoware_api_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_autoware_api_launch \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/system/autoware_default_adapi_universe,target=/autoware/src/universe/autoware_universe/system/autoware_default_adapi_universe \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/system/autoware_diagnostic_graph_utils,target=/autoware/src/universe/autoware_universe/system/autoware_diagnostic_graph_utils \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-api-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-api-pkgs.txt \
  && cat /tmp/rosdep-api-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && /scripts/build_and_clean.sh "${CCACHE_DIR}" /opt/autoware

# =============================================================================
# Runtime stage: api
# =============================================================================
FROM $COMMON_BASE_IMAGE AS api
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Copy rosdep dependency lists
COPY --from=api-devel /tmp/rosdep-universe-common-exec-pkgs.txt /tmp/rosdep-universe-common-exec-pkgs.txt
COPY --from=api-devel /tmp/rosdep-api-exec-pkgs.txt /tmp/rosdep-api-exec-pkgs.txt

# Set up runtime environment and install rosdep dependencies
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module all --no-nvidia --no-cuda-drivers --runtime openadkit --ros-distro $ROS_DISTRO \
  && pipx uninstall ansible \
  && apt-get update \
  && cat /tmp/rosdep-universe-common-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && cat /tmp/rosdep-api-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && /scripts/cleanup_system.sh $ROS_DISTRO

# Copy binaries from devel stage
COPY --from=api-devel /opt/autoware /opt/autoware

ENTRYPOINT ["/scripts/autoware_entrypoint.sh"]
CMD ["/bin/bash"]
