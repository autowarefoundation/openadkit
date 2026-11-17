# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom,UndefinedVar
ARG UNIVERSE_COMMON_DEVEL_IMAGE
ARG UNIVERSE_COMMON_IMAGE

# =============================================================================
# Build stage: vehicle-system-devel
# =============================================================================
FROM ${UNIVERSE_COMMON_DEVEL_IMAGE} AS vehicle-system-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

COPY --parents --chown=${USERNAME}:${USERNAME} \
    autoware/src/**/package.xml \
    /tmp/

RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    rosdep install -y --from-paths /tmp/autoware/src /opt/autoware/*/share \
      --ignore-src --rosdistro "${ROS_DISTRO}" \
      --dependency-types=build --dependency-types=build_export \
      --dependency-types=buildtool --dependency-types=buildtool_export \
      --dependency-types=test

RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=cache,id=ccache-${ROS_DISTRO},target=/home/aw/.ccache,uid=1000,gid=1000 \
    mkdir -p /opt/openadkit && \
    printf '%s\n' \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_vehicle_launch \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_system_launch \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_autoware_api_launch \
        /tmp/autoware/src/launcher/autoware_launch/sensor_kit/carla_sensor_kit_launch/carla_sensor_kit_description \
        /tmp/autoware/src/launcher/autoware_launch/sensor_kit/carla_sensor_kit_launch/carla_sensor_kit_launch \
        /tmp/autoware/src/launcher/autoware_launch/sensor_kit/sample_sensor_kit_launch/common_sensor_launch \
        /tmp/autoware/src/launcher/autoware_launch/sensor_kit/sample_sensor_kit_launch/sample_sensor_kit_description \
        /tmp/autoware/src/launcher/autoware_launch/sensor_kit/sample_sensor_kit_launch/sample_sensor_kit_launch \
        /tmp/autoware/src/launcher/autoware_launch/vehicle/sample_vehicle_launch/sample_vehicle_description \
        /tmp/autoware/src/launcher/autoware_launch/vehicle/sample_vehicle_launch/sample_vehicle_launch \
        /tmp/autoware/src/universe/autoware_universe/vehicle \
        /tmp/autoware/src/universe/autoware_universe/system \
        /tmp/autoware/src/universe/autoware_universe/simulator/autoware_dummy_diag_publisher \
        /tmp/autoware/src/universe/autoware_universe/planning/planning_validator \
        /tmp/autoware/src/sensor_component/external/sensor_component_description \
      > /opt/openadkit/colcon-base-paths && \
    colcon_base_paths=$(tr '\n' ' ' < /opt/openadkit/colcon-base-paths) && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    colcon build \
      --base-paths ${colcon_base_paths} \
      --install-base /opt/autoware \
      --cmake-args -DCMAKE_BUILD_TYPE=Release && \
    rm -rf build log

# This image's launch and config packages, in their own layer after the
# compile (components/shared/launch-packages.sh).
RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/shared/launch-packages.sh,target=/tmp/launch-packages.sh \
    bash /tmp/launch-packages.sh autoware_sensing_launch autoware_sensor_driver_launch

RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    rosdep install -y --from-paths /tmp/autoware/src /opt/autoware/*/share \
      --ignore-src --rosdistro "${ROS_DISTRO}" \
      --dependency-types=exec && \
    rm -rf /tmp/autoware

# =============================================================================
# Runtime stage: vehicle-system
# =============================================================================
FROM ${UNIVERSE_COMMON_IMAGE} AS vehicle-system
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root
# Install the packages this image adds to universe-common, and only those
# (install-packages.sh).
RUN --mount=from=vehicle-system-devel,source=/opt/autoware,target=/mnt/autoware \
    --mount=type=bind,source=components/shared/install-packages.sh,target=/tmp/install-packages.sh \
    bash /tmp/install-packages.sh /mnt/autoware /opt/autoware

RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/shared/runtime-deps.sh,target=/tmp/runtime-deps.sh \
    --mount=type=bind,source=components/shared/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    bash /tmp/runtime-deps.sh /tmp/autoware/src && \
    bash /tmp/runtime-cleanup.sh

# Fail when a compiled binary cannot load its libraries in this image
# (components/shared/check-linked-libs.sh).
RUN --mount=type=bind,source=components/shared/check-linked-libs.sh,target=/tmp/check-linked-libs.sh \
    bash /tmp/check-linked-libs.sh
