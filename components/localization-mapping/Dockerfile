# Dockerfile - Builds localization-mapping runtime image
ARG COMMON_BASE_IMAGE=ghcr.io/autowarefoundation/openadkit-common:base
ARG COMMON_DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common:devel
ARG ROS_DISTRO=humble

# =============================================================================
# Build stage: localization-mapping-devel
# =============================================================================
FROM $COMMON_DEVEL_IMAGE AS localization-mapping-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install rosdep dependencies and build packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
--mount=type=bind,source=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_localization_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_localization_launch \
  --mount=type=bind,source=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_map_launch,target=/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_map_launch \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/localization,target=/autoware/src/universe/autoware_universe/localization \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/map,target=/autoware/src/universe/autoware_universe/map \
  # TODO(youtalk): Remove COPYs when https://github.com/autowarefoundation/autoware_universe/issues/10282 is resolved
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions,target=/autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor,target=/autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor \
  --mount=type=bind,source=/autoware/src/universe/autoware_universe/system/autoware_default_adapi_helpers/autoware_automatic_pose_initializer,target=/autoware/src/universe/autoware_universe/system/autoware_default_adapi_helpers/autoware_automatic_pose_initializer \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-localization-mapping-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-localization-mapping-pkgs.txt \
  && cat /tmp/rosdep-localization-mapping-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && /scripts/build_and_clean.sh "${CCACHE_DIR}" /opt/autoware

# =============================================================================
# Runtime stage: localization-mapping
# =============================================================================
FROM $COMMON_BASE_IMAGE AS localization-mapping
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Copy rosdep dependency lists
COPY --from=localization-mapping-devel /tmp/rosdep-universe-common-exec-pkgs.txt /tmp/rosdep-universe-common-exec-pkgs.txt
COPY --from=localization-mapping-devel /tmp/rosdep-localization-mapping-exec-pkgs.txt /tmp/rosdep-localization-mapping-exec-pkgs.txt

# Set up runtime environment
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module all --no-nvidia --no-cuda-drivers --runtime openadkit --ros-distro $ROS_DISTRO \
  && pipx uninstall ansible \
  && apt-get update \
  && cat /tmp/rosdep-universe-common-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && cat /tmp/rosdep-localization-mapping-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && /scripts/cleanup_system.sh $ROS_DISTRO

# Copy binaries from devel stage
COPY --from=localization-mapping-devel /opt/autoware /opt/autoware

ENTRYPOINT ["/scripts/autoware_entrypoint.sh"]
CMD ["/bin/bash"]
