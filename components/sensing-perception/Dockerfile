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
      "${pkg_prefix}/share/colcon-core/packages" && \
    touch "${pkg_prefix}/share/ament_index/resource_index/packages/autoware_ground_segmentation_cuda" && \
    : > "${pkg_prefix}/share/colcon-core/packages/autoware_ground_segmentation_cuda" && \
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
RUN --mount=from=sensing-perception-devel,source=/opt/autoware,target=/mnt/autoware \
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
