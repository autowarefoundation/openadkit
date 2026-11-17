# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom,UndefinedVar
ARG CORE_DEVEL_IMAGE
ARG BASE_IMAGE

# The upstream base core-devel builds on; the snapshot check below reads which
# ROS packages core added over it.
FROM ${BASE_IMAGE} AS upstream-base

# =============================================================================
# Stage: universe-common-build
# Compiles the universe-common slice into /opt/autoware on top of core-devel.
# Components compile on this stage. It has no per-build step, so CI can push it
# with the same digest while its inputs are unchanged and the component builds
# stay cached (.github/scripts/build.py).
# =============================================================================
FROM ${CORE_DEVEL_IMAGE} AS universe-common-build
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install ROS packages from the snapshot the upstream images were built from;
# fails when ROS_SNAPSHOT does not match them (components/shared/ros-snapshot).
ARG ROS_SNAPSHOT
LABEL org.autoware.openadkit.ros-snapshot="${ROS_SNAPSHOT}"
RUN --mount=type=bind,source=components/shared/ros-snapshot,target=/tmp/ros-snapshot \
    --mount=from=upstream-base,source=/var/lib/dpkg,target=/tmp/base-dpkg \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    bash /tmp/ros-snapshot/ros-snapshot.sh "${ROS_SNAPSHOT}" --check /tmp/base-dpkg

# rosdep install for the universe-common slice (build/test deps).
# Broad glob so rosdep sees all universe packages as local via --ignore-src,
# preventing cross-component exec_depend failures (e.g. simulator referencing
# planning packages). colcon build is still scoped by --base-paths below.
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
# The acados venv only generates solver code during colcon builds; nothing
# installs into it afterwards, so it keeps no pip. pipx then drops ansible, the
# developer tools inherited from core-devel (pre-commit, clang-format) and its
# shared pip, which uninstall-all keeps (~/.local/pipx on Humble,
# ~/.local/share/pipx on Jazzy).
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
    sudo /opt/acados/.venv/bin/python -m pip uninstall -y pip && \
    pipx uninstall-all && \
    rm -rf /home/aw/.local/pipx /home/aw/.local/share/pipx
USER root

ENV CMAKE_PREFIX_PATH="/opt/acados${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
ENV ACADOS_SOURCE_DIR="/opt/acados"
ENV LD_LIBRARY_PATH="/opt/acados/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# colcon build the universe-common slice into /opt/autoware (next to core).
RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=cache,id=ccache-${ROS_DISTRO},target=/home/aw/.ccache,uid=1000,gid=1000 \
    mkdir -p /opt/openadkit && \
    printf '%s\n' \
        /tmp/autoware/src/universe/autoware_universe/common \
        /tmp/autoware/src/*/*/*/autoware_cuda_dependency_meta \
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
      > /opt/openadkit/colcon-base-paths && \
    colcon_base_paths=$(tr '\n' ' ' < /opt/openadkit/colcon-base-paths) && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    . /opt/autoware/setup.sh && \
    colcon build \
      --base-paths ${colcon_base_paths} \
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
# Stage: universe-common-devel
# The published development image: the build stage plus Ubuntu's updates the
# pinned upstream base image lags on (components/shared/security-refresh.sh).
# =============================================================================
FROM universe-common-build AS universe-common-devel
ARG ROS_DISTRO
ARG SECURITY_REFRESH=0
RUN --mount=type=bind,source=components/shared/security-refresh.sh,target=/tmp/security-refresh.sh \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    echo "openadkit security refresh ${SECURITY_REFRESH}" && \
    bash /tmp/security-refresh.sh

# =============================================================================
# Stage: universe-common
# Runtime variant: exec deps + the compiled tree, on top of the lean base.
# =============================================================================
FROM ${BASE_IMAGE} AS universe-common
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root

# Every package installed from here on, in this image and the component images
# on it, leaves out what only a compiler reads (headers, static libraries).
COPY components/shared/dpkg-runtime.cfg /etc/dpkg/dpkg.cfg.d/openadkit-runtime

# Install ROS packages from the same snapshot as the devel stage; fails when
# the base image's ROS packages differ from it.
ARG ROS_SNAPSHOT
LABEL org.autoware.openadkit.ros-snapshot="${ROS_SNAPSHOT}"
RUN --mount=type=bind,source=components/shared/ros-snapshot,target=/tmp/ros-snapshot \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    bash /tmp/ros-snapshot/ros-snapshot.sh "${ROS_SNAPSHOT}" --check

# ${BASE_IMAGE} has no /opt/autoware: install the compiled tree, without the
# RViz plugins, which the visualizer installs (install-packages.sh).
# Of acados, the compiled tree only links its shared libraries; its sources,
# build tree and code-generation venv stay in the devel image.
RUN --mount=from=universe-common-build,source=/opt/acados/lib,target=/mnt/acados-lib \
    --mount=from=universe-common-build,source=/opt/autoware,target=/mnt/autoware \
    --mount=type=bind,source=components/shared/install-packages.sh,target=/tmp/install-packages.sh \
    --mount=type=bind,source=components/shared/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    mkdir /opt/acados && \
    cp -a /mnt/acados-lib /opt/acados/lib && \
    bash /tmp/install-packages.sh /mnt/autoware /opt/autoware && \
    bash /tmp/runtime-cleanup.sh opt

ENV LD_LIBRARY_PATH="/opt/acados/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/shared/runtime-deps.sh,target=/tmp/runtime-deps.sh \
    --mount=type=bind,source=components/shared/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      geographiclib-tools \
      "ros-${ROS_DISTRO}-domain-bridge" \
      "ros-${ROS_DISTRO}-topic-tools" && \
    geographiclib-get-geoids egm2008-1 && \
    bash /tmp/runtime-deps.sh /tmp/autoware/src && \
    bash /tmp/runtime-cleanup.sh

# Same refresh as the devel image: a per-build SECURITY_REFRESH change only
# re-runs this step and the check after it.
ARG SECURITY_REFRESH=0
RUN --mount=type=bind,source=components/shared/security-refresh.sh,target=/tmp/security-refresh.sh \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    echo "openadkit security refresh ${SECURITY_REFRESH}" && \
    bash /tmp/security-refresh.sh

# Fail when a compiled binary cannot load its libraries in this image, after
# the refresh (components/shared/check-linked-libs.sh).
RUN --mount=type=bind,source=components/shared/check-linked-libs.sh,target=/tmp/check-linked-libs.sh \
    bash /tmp/check-linked-libs.sh

# On every start: run as the host user, source ROS and Autoware, and layer the
# kit's config overrides and overlay workspace on top (components/shared/entrypoint).
COPY components/shared/entrypoint/entrypoint.sh components/shared/entrypoint/overlay.py /opt/openadkit/
COPY components/shared/entrypoint/health/ /opt/openadkit/health/
ENTRYPOINT ["/opt/openadkit/entrypoint.sh"]
CMD ["/bin/bash"]
