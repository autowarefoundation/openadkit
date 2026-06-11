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
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    colcon build \
      --base-paths \
        /tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_autoware_api_launch \
        /tmp/autoware/src/universe/autoware_universe/system/autoware_default_adapi_universe \
        /tmp/autoware/src/universe/autoware_universe/system/autoware_diagnostic_graph_utils \
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
# Runtime stage: api
# =============================================================================
FROM ${UNIVERSE_COMMON_IMAGE} AS api
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root
COPY --from=api-devel /opt/autoware /opt/autoware
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
