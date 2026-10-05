# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom,UndefinedVar
ARG UNIVERSE_COMMON_DEVEL_IMAGE
ARG UNIVERSE_COMMON_IMAGE

# =============================================================================
# Build stage: api-devel
# =============================================================================
FROM ${UNIVERSE_COMMON_DEVEL_IMAGE} AS api-devel
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
        /tmp/autoware/src/launcher/autoware_launch/vehicle/sample_vehicle_launch/sample_vehicle_description \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_autoware_api_launch \
        /tmp/autoware/src/universe/autoware_universe/system/autoware_default_adapi_universe \
        /tmp/autoware/src/universe/autoware_universe/system/autoware_diagnostic_graph_utils \
      > /opt/openadkit/colcon-base-paths && \
    colcon_base_paths=$(tr '\n' ' ' < /opt/openadkit/colcon-base-paths) && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    colcon build \
      --base-paths ${colcon_base_paths} \
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

# Align the packages the compiled tree links against with the current apt feed
# and rebuild when any of them moved; the first compile above stays cached when
# nothing did. Re-runs every build via ROS_ALIGN_STAMP (components/link-lock).
ARG ROS_ALIGN_STAMP=0
RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/link-lock,target=/tmp/link-lock \
    --mount=type=cache,id=ccache-${ROS_DISTRO},target=/home/aw/.ccache,uid=1000,gid=1000 \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    echo "ros align ${ROS_ALIGN_STAMP}" && \
    bash /tmp/link-lock/align.sh

# =============================================================================
# Runtime stage: api
# =============================================================================
FROM ${UNIVERSE_COMMON_IMAGE} AS api
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root
RUN --mount=from=api-devel,source=/opt/autoware,target=/mnt/autoware \
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
# against and verify them (components/link-lock).
RUN --mount=from=api-devel,source=/opt/openadkit/link-lock.txt,target=/tmp/link-lock.txt \
    --mount=type=bind,source=components/link-lock,target=/tmp/link-lock \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    bash /tmp/link-lock/lock.sh install --lock /tmp/link-lock.txt && \
    bash /tmp/link-lock/lock.sh verify --lock /tmp/link-lock.txt
