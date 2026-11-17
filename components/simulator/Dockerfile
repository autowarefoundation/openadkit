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
    mkdir -p /opt/openadkit && \
    printf '%s\n' \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_simulator_launch \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_perception_launch \
        /tmp/autoware/src/launcher/autoware_launch/sensor_kit/carla_sensor_kit_launch/carla_sensor_kit_description \
        /tmp/autoware/src/launcher/autoware_launch/sensor_kit/carla_sensor_kit_launch/carla_sensor_kit_launch \
        /tmp/autoware/src/launcher/autoware_launch/vehicle/sample_vehicle_launch/sample_vehicle_description \
        /tmp/autoware/src/universe/autoware_universe/simulator \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_shape_estimation \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_multi_object_tracker \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_crosswalk_traffic_light_estimator \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_elevation_map_loader \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_detected_object_feature_remover \
        /tmp/autoware/src/universe/autoware_universe/perception/perception_utils \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_arbiter \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_category_merger \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_classifier \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_fine_detector \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_map_based_detector \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_multi_camera_fusion \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_occlusion_predictor \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_selector \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_traffic_light_visualization \
        /tmp/autoware/src/*/*/*/autoware_tensorrt_common \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_probabilistic_occupancy_grid_map \
        /tmp/autoware/src/universe/autoware_universe/perception/autoware_map_based_prediction \
        /tmp/autoware/src/*/*/*/autoware_cuda_utils \
        /tmp/autoware/src/universe/autoware_universe/sensing/autoware_pointcloud_preprocessor \
        /tmp/autoware/src/universe/autoware_universe/sensing/autoware_pcl_extensions \
        /tmp/autoware/src/universe/autoware_universe/vehicle/autoware_raw_vehicle_cmd_converter \
        /tmp/autoware/src/universe/autoware_universe/system/autoware_dummy_infrastructure \
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
    bash /tmp/launch-packages.sh autoware_perception_launch autoware_perception_config \
      autoware_localization_launch autoware_localization_config

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
# Install the packages this image adds to universe-common, and only those
# (install-packages.sh).
RUN --mount=from=simulator-devel,source=/opt/autoware,target=/mnt/autoware \
    --mount=type=bind,source=components/shared/install-packages.sh,target=/tmp/install-packages.sh \
    bash /tmp/install-packages.sh /mnt/autoware /opt/autoware

RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/shared/runtime-deps.sh,target=/tmp/runtime-deps.sh \
    --mount=type=bind,source=components/shared/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    bash /tmp/runtime-deps.sh /tmp/autoware/src && \
    bash /tmp/runtime-cleanup.sh

# The CARLA bridge (autoware_carla_interface, built above) needs the CARLA
# Python client and two ROS tools. CARLA publishes its client for x86_64 only,
# and carla-simulation runs only on amd64, so arm64 images go without it.
ARG TARGETARCH
ARG CARLA_PYTHON_VERSION=0.9.16
RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    if [ "${TARGETARCH}" = amd64 ]; then \
      apt-get update && \
      apt-get install -y --no-install-recommends \
        python3-pip \
        "ros-${ROS_DISTRO}-compressed-image-transport" \
        "ros-${ROS_DISTRO}-topic-tools" && \
      PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --no-cache-dir \
        "carla==${CARLA_PYTHON_VERSION}" transforms3d; \
    fi

# Fail when a compiled binary cannot load its libraries in this image
# (components/shared/check-linked-libs.sh).
RUN --mount=type=bind,source=components/shared/check-linked-libs.sh,target=/tmp/check-linked-libs.sh \
    bash /tmp/check-linked-libs.sh
