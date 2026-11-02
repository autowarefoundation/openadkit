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
LABEL org.opencontainers.image.ros-snapshot="${ROS_SNAPSHOT}"
RUN --mount=type=bind,source=components/shared/ros-snapshot,target=/tmp/ros-snapshot \
    --mount=from=upstream-base,source=/var/lib/dpkg,target=/tmp/base-dpkg \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    bash /tmp/ros-snapshot/ros-snapshot.sh "${ROS_SNAPSHOT}" --check /tmp/base-dpkg

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
ENV AUTOWARE_RUNTIME=1

# Install ROS packages from the same snapshot as the devel stage; fails when
# the base image's ROS packages differ from it.
ARG ROS_SNAPSHOT
LABEL org.opencontainers.image.ros-snapshot="${ROS_SNAPSHOT}"
RUN --mount=type=bind,source=components/shared/ros-snapshot,target=/tmp/ros-snapshot \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    bash /tmp/ros-snapshot/ros-snapshot.sh "${ROS_SNAPSHOT}" --check

# ${BASE_IMAGE} has no /opt/autoware. Copy the tree into place; cp -a src/. dest/
# would require dest to exist, and if dest later appears this must not nest.
# Of acados, the compiled tree only links its shared libraries; its sources,
# build tree and code-generation venv stay in the devel image.
RUN --mount=from=universe-common-build,source=/opt/acados/lib,target=/mnt/acados-lib \
    --mount=from=universe-common-build,source=/opt/autoware,target=/mnt/autoware \
    --mount=type=bind,source=components/shared/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    mkdir /opt/acados && \
    cp -a /mnt/acados-lib /opt/acados/lib && \
    cp -a /mnt/autoware /opt/autoware && \
    find /opt/autoware -name '*.so' -exec strip --strip-unneeded {} + && \
    bash /tmp/runtime-cleanup.sh opt

ENV LD_LIBRARY_PATH="/opt/acados/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

RUN --mount=type=bind,source=autoware/src,target=/tmp/autoware/src \
    --mount=type=bind,source=components/shared/runtime-cleanup.sh,target=/tmp/runtime-cleanup.sh \
    --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      geographiclib-tools \
      "ros-${ROS_DISTRO}-domain-bridge" \
      "ros-${ROS_DISTRO}-topic-tools" && \
    geographiclib-get-geoids egm2008-1 && \
    . "/opt/ros/${ROS_DISTRO}/setup.sh" && \
    internal_packages="$(colcon list --base-paths /tmp/autoware/src --names-only | tr '\n' ' ')" && \
    rosdep install -y --from-paths /opt/autoware/*/share \
      --dependency-types=exec --ignore-src --rosdistro "${ROS_DISTRO}" \
      --skip-keys "${internal_packages}" && \
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

# Integrator layer (components/shared/entrypoint): on every start, layer config overrides
# and the overlay workspace on top of Autoware, after the upstream entrypoint
# has sourced ROS and switched to the aw user.
COPY components/shared/entrypoint/openadkit-hook.sh components/shared/entrypoint/overlay.py /opt/openadkit/
ENTRYPOINT ["/docker-entrypoint.sh", "/opt/openadkit/openadkit-hook.sh"]
CMD ["/bin/bash"]
