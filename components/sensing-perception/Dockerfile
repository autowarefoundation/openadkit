# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom,UndefinedVar
ARG UNIVERSE_COMMON_DEVEL_IMAGE
ARG UNIVERSE_COMMON_IMAGE

# =============================================================================
# Build stage: sensing-perception-devel
# =============================================================================
FROM ${UNIVERSE_COMMON_DEVEL_IMAGE} AS sensing-perception-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO
ARG COLCON_BASE_PATHS

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

# The CPU build skips this CUDA package, but upstream launch still resolves its
# package share path while declaring defaults with CUDA disabled.
RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=cache,id=ccache-${ROS_DISTRO},target=/home/aw/.ccache,uid=1000,gid=1000 \
    mkdir -p /opt/openadkit && \
    printf '%s\n' ${COLCON_BASE_PATHS} > /opt/openadkit/colcon-base-paths && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    colcon build \
      --base-paths ${COLCON_BASE_PATHS} \
      --install-base /opt/autoware \
      --cmake-args -DCMAKE_BUILD_TYPE=Release && \
    pkg_prefix=/opt/autoware/autoware_ground_segmentation_cuda && \
    install -d \
      "${pkg_prefix}/share/ament_index/resource_index/packages" \
      "${pkg_prefix}/share/autoware_ground_segmentation_cuda" \
      "${pkg_prefix}/share/colcon-core/packages" \
      /opt/autoware/share/colcon-core/packages && \
    touch "${pkg_prefix}/share/ament_index/resource_index/packages/autoware_ground_segmentation_cuda" && \
    : > "${pkg_prefix}/share/colcon-core/packages/autoware_ground_segmentation_cuda" && \
    : > /opt/autoware/share/colcon-core/packages/autoware_ground_segmentation_cuda && \
    printf '%s\n' \
      'source;share/autoware_ground_segmentation_cuda/local_setup.dsv' \
      > "${pkg_prefix}/share/autoware_ground_segmentation_cuda/package.dsv" && \
    printf '%s\n' \
      'prepend-non-duplicate;AMENT_PREFIX_PATH;' \
      'prepend-non-duplicate;CMAKE_PREFIX_PATH;' \
      > "${pkg_prefix}/share/autoware_ground_segmentation_cuda/local_setup.dsv" && \
    cp -r \
      /tmp/autoware/src/universe/autoware_universe/perception/autoware_ground_segmentation_cuda/config \
      /tmp/autoware/src/universe/autoware_universe/perception/autoware_ground_segmentation_cuda/launch \
      /tmp/autoware/src/universe/autoware_universe/perception/autoware_ground_segmentation_cuda/package.xml \
      "${pkg_prefix}/share/autoware_ground_segmentation_cuda/" && \
    rm -rf build log

# This image's launch and config packages, in their own layer after the
# compile (components/shared/launch-packages.sh).
RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/shared/launch-packages.sh,target=/tmp/launch-packages.sh \
    bash /tmp/launch-packages.sh autoware_sensing_launch autoware_sensor_driver_launch autoware_perception_launch autoware_perception_config

RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    rosdep install -y --from-paths /tmp/autoware/src /opt/autoware/*/share \
      --ignore-src --rosdistro "${ROS_DISTRO}" \
      --dependency-types=exec && \
    rm -rf /tmp/autoware

# =============================================================================
# Runtime stage: sensing-perception
# =============================================================================
FROM ${UNIVERSE_COMMON_IMAGE} AS sensing-perception
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root
# Install the packages this image adds to universe-common, and only those
# (install-packages.sh).
RUN --mount=from=sensing-perception-devel,source=/opt/autoware,target=/mnt/autoware \
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
