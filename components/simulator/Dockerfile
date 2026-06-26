# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom,UndefinedVar
ARG UNIVERSE_COMMON_DEVEL_IMAGE
ARG UNIVERSE_COMMON_IMAGE

# =============================================================================
# Build stage: simulator-devel
# =============================================================================
FROM ${UNIVERSE_COMMON_DEVEL_IMAGE} AS simulator-devel
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
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    colcon build \
      --base-paths \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_simulator_launch \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_perception_launch \
        /tmp/autoware/src/launcher/autoware_launch/vehicle/sample_vehicle_launch/sample_vehicle_description \
        /tmp/autoware/src/universe/autoware_universe/simulator \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_shape_estimation \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_multi_object_tracker \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_elevation_map_loader \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_detected_object_feature_remover \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_tensorrt_common \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_probabilistic_occupancy_grid_map \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_map_based_prediction \
        /tmp/autoware/src/universe/autoware_universe/sensing/autoware_cuda_utils \
        /tmp/autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor \
        /tmp/autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions \
        /tmp/autoware/src/universe/autoware_universe/vehicle/autoware_raw_vehicle_cmd_converter \
        /tmp/autoware/src/universe/autoware_universe/system/autoware_dummy_infrastructure \
      --install-base /opt/autoware \
      --cmake-args -DCMAKE_BUILD_TYPE=Release && \
    rm -rf build log

RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    rosdep install -y --from-paths /tmp/autoware/src /opt/autoware/*/share \
      --ignore-src --rosdistro "${ROS_DISTRO}" \
      --dependency-types=exec && \
    rm -rf /tmp/autoware

# =============================================================================
# Runtime stage: simulator
# =============================================================================
FROM ${UNIVERSE_COMMON_IMAGE} AS simulator
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root
COPY --from=simulator-devel /opt/autoware /opt/autoware
RUN find /opt/autoware -name '*.so' -exec strip --strip-unneeded {} +

COPY --parents --chown=${USERNAME}:${USERNAME} \
    autoware/src/**/package.xml \
    /tmp/

RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    rosdep install -y --from-paths /tmp /opt/autoware/*/share \
      --dependency-types=exec --ignore-src --rosdistro "${ROS_DISTRO}" && \
    rm -rf /tmp/*
