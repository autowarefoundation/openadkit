# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom,UndefinedVar
ARG UNIVERSE_COMMON_DEVEL_IMAGE
ARG UNIVERSE_COMMON_IMAGE

# =============================================================================
# Build stage: planning-control-devel
# =============================================================================
FROM ${UNIVERSE_COMMON_DEVEL_IMAGE} AS planning-control-devel
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
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_control_launch \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_planning_launch \
        /tmp/autoware/src/launcher/autoware_launch/vehicle/sample_vehicle_launch/sample_vehicle_description \
        /tmp/autoware/src/universe/autoware_universe/control \
        /tmp/autoware/src/universe/autoware_universe/planning \
        /tmp/autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions \
        /tmp/autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor \
        /tmp/autoware/src/universe/autoware_universe/sensing/autoware_cuda_utils \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_tensorrt_common \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_tensorrt_plugins \
        /tmp/autoware/src/universe/autoware_universe/vehicle/autoware_external_cmd_converter \
        /tmp/autoware/src/universe/autoware_universe/vehicle/autoware_raw_vehicle_cmd_converter \
        /tmp/autoware/src/universe/autoware_universe/system/autoware_command_mode_types \
      > /opt/openadkit/colcon-base-paths && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    colcon build \
      --base-paths $(cat /opt/openadkit/colcon-base-paths) \
      --install-base /opt/autoware \
      --cmake-args -DCMAKE_BUILD_TYPE=Release && \
    rm -rf build log

# Align the packages the compiled tree links against with the current apt feed
# and rebuild when any of them moved; the first compile above stays cached when
# nothing did. Re-runs every build via ROS_REFRESH (components/ros-align.sh).
ARG ROS_REFRESH=0
RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/link-lock.sh,target=/tmp/link-lock.sh \
    --mount=type=bind,source=components/ros-refresh.sh,target=/tmp/ros-refresh.sh \
    --mount=type=bind,source=components/ros-align.sh,target=/tmp/ros-align.sh \
    --mount=type=cache,id=ccache-${ROS_DISTRO},target=/home/aw/.ccache,uid=1000,gid=1000 \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    echo "ros align ${ROS_REFRESH}" && \
    bash /tmp/ros-align.sh

RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    rosdep install -y --from-paths /tmp/autoware/src /opt/autoware/*/share \
      --ignore-src --rosdistro "${ROS_DISTRO}" \
      --dependency-types=exec && \
    rm -rf /tmp/autoware

# =============================================================================
# Runtime stage: planning-control
# =============================================================================
FROM ${UNIVERSE_COMMON_IMAGE} AS planning-control
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root
RUN --mount=from=planning-control-devel,source=/opt/autoware,target=/mnt/autoware \
    --mount=type=bind,source=components/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    cp -a /mnt/autoware/. /opt/autoware/ && \
    find /opt/autoware -name '*.so' -exec strip --strip-unneeded {} + && \
    bash /tmp/runtime-cleanup.sh opt

RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    internal_packages="$(colcon list --base-paths /tmp/autoware/src --names-only | tr '\n' ' ')" && \
    rosdep install -y --from-paths /opt/autoware/*/share \
      --dependency-types=exec --ignore-src --rosdistro "${ROS_DISTRO}" \
      --skip-keys "${internal_packages}" && \
    bash /tmp/runtime-cleanup.sh

# Install the exact package versions the matching devel stage compiled
# against and verify them (components/ros-refresh.sh, components/link-lock.sh).
RUN --mount=from=planning-control-devel,source=/opt/openadkit/link-lock.txt,target=/tmp/link-lock.txt \
    --mount=type=bind,source=components/link-lock.sh,target=/tmp/link-lock.sh \
    --mount=type=bind,source=components/ros-refresh.sh,target=/tmp/ros-refresh.sh \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    bash /tmp/ros-refresh.sh install --lock /tmp/link-lock.txt && \
    bash /tmp/link-lock.sh verify /tmp/link-lock.txt
