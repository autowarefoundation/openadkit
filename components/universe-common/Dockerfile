# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom,UndefinedVar
ARG CORE_DEVEL_IMAGE
ARG BASE_IMAGE

# =============================================================================
# Stage: universe-common-devel
# Compiles the universe-common slice into /opt/autoware on top of core-devel.
# =============================================================================
FROM ${CORE_DEVEL_IMAGE} AS universe-common-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# rosdep install for the universe-common slice (build/test deps).
# Broad glob so rosdep sees all universe packages as local via --ignore-src,
# preventing cross-component exec_depend failures (e.g. simulator referencing
# planning-control packages). colcon build is still scoped by --base-paths below.
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

# Install acados (BLASFEO + HPIPM + acados) via the upstream ansible playbook.
# Must run as ${USERNAME} because the playbook uses pipx in the aw user directory.
USER ${USERNAME}
RUN --mount=type=bind,source=autoware/ansible-galaxy-requirements.yaml,target=/tmp/ansible/ansible-galaxy-requirements.yaml \
    --mount=type=bind,source=autoware/ansible,target=/tmp/ansible/ansible \
    --mount=type=cache,id=pip-cache,target=/home/aw/.cache/pip,uid=1000,gid=1000 \
    --mount=type=cache,id=pipx-cache,target=/home/aw/.cache/pipx,uid=1000,gid=1000 \
    pipx install --include-deps "ansible==10.*" && \
    cd /tmp/ansible && \
    ansible-galaxy collection install -f -r ansible-galaxy-requirements.yaml && \
    ansible-playbook autoware.dev_env.install_image_deps \
      --tags acados \
      -e "rosdistro=${ROS_DISTRO}" && \
    sudo rm -rf /opt/acados/.git /opt/acados/examples /opt/acados/docs /opt/acados/test && \
    pipx uninstall ansible
USER root

ENV CMAKE_PREFIX_PATH="/opt/acados${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
ENV ACADOS_SOURCE_DIR="/opt/acados"
ENV LD_LIBRARY_PATH="/opt/acados/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# colcon build the universe-common slice into /opt/autoware (next to core).
RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=cache,id=ccache-${ROS_DISTRO},target=/home/aw/.ccache,uid=1000,gid=1000 \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    colcon build \
      --base-paths \
        /tmp/autoware/src/universe/autoware_universe/common \
        /tmp/autoware/src/universe/autoware_universe/evaluator \
        /tmp/autoware/src/universe/external/eagleye \
        /tmp/autoware/src/universe/external/glog \
        /tmp/autoware/src/universe/external/llh_converter \
        /tmp/autoware/src/universe/external/managed_transform_buffer \
        /tmp/autoware/src/universe/external/morai_msgs \
        /tmp/autoware/src/universe/external/muSSP \
        /tmp/autoware/src/universe/external/pointcloud_to_laserscan \
        /tmp/autoware/src/universe/external/rtklib_ros_bridge \
        /tmp/autoware/src/universe/external/tier4_autoware_msgs \
        /tmp/autoware/src/launcher/autoware_launch/autoware_launch \
        /tmp/autoware/src/middleware/external \
      --install-base /opt/autoware \
      --cmake-args -DCMAKE_BUILD_TYPE=Release && \
    rm -rf build log

# Exec-only rosdep for the universe-common slice.
RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    rosdep install -y --from-paths /tmp/autoware/src /opt/autoware/*/share \
      --ignore-src --rosdistro "${ROS_DISTRO}" \
      --dependency-types=exec && \
    rm -rf /tmp/autoware

# =============================================================================
# Stage: universe-common
# Runtime variant: exec deps + the compiled tree, on top of the lean base.
# =============================================================================
FROM ${BASE_IMAGE} AS universe-common
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root
ENV AUTOWARE_RUNTIME=1
RUN --mount=from=universe-common-devel,source=/opt/acados,target=/mnt/acados \
    --mount=from=universe-common-devel,source=/opt/autoware,target=/mnt/autoware \
    --mount=type=bind,source=components/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    cp -a /mnt/acados /opt/acados && \
    cp -a /mnt/autoware /opt/autoware && \
    find /opt/autoware -name '*.so' -exec strip --strip-unneeded {} + && \
    bash /tmp/runtime-cleanup.sh opt

ENV CMAKE_PREFIX_PATH="/opt/acados${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
ENV ACADOS_SOURCE_DIR="/opt/acados"
ENV LD_LIBRARY_PATH="/opt/acados/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

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
