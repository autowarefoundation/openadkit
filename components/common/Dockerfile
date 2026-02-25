# Dockerfile - Builds common-base and common-devel images with CUDA flavors
ARG BASE_IMAGE=ros:humble-ros-base-jammy
ARG ROS_DISTRO=humble

# =============================================================================
# Stage: common-base
# Base image with ROS and primary dependencies
# =============================================================================
FROM $BASE_IMAGE AS common-base
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO
ENV CCACHE_DIR="/root/.ccache"
WORKDIR /autoware

# Copy files
COPY autoware/setup-dev-env.sh autoware/ansible-galaxy-requirements.yaml autoware/amd64.env autoware/amd64_jazzy.env autoware/arm64.env /autoware/
COPY autoware/ansible/ /autoware/ansible/
COPY components/common/scripts/ /scripts/
RUN chmod -R +x /scripts/

# Disable installing suggested and recommended packages
RUN echo 'APT::Install-Recommends "false";' > /etc/apt/apt.conf.d/99-disable-extra-packages; \
    echo 'APT::Install-Suggests "false";' >> /etc/apt/apt.conf.d/99-disable-extra-packages

# Install apt packages and add GitHub to known hosts for private repositories
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
  && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' >/etc/apt/apt.conf.d/keep-cache
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
  gosu \
  ssh \
  && /scripts/cleanup_apt.sh \
  && mkdir -p ~/.ssh \
  && ssh-keyscan github.com >> ~/.ssh/known_hosts

# Set up base environment
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module base --no-nvidia --no-cuda-drivers --runtime openadkit --ros-distro "$ROS_DISTRO" \
  && pipx uninstall ansible \
  && /scripts/cleanup_apt.sh true \
  && echo "source /opt/ros/${ROS_DISTRO}/setup.bash" > /etc/bash.bashrc

# =============================================================================
# Stage: common-base-cuda
# Base image with CUDA support
# =============================================================================
FROM common-base AS common-base-cuda
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Set up CUDA runtime environment
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh -y --module base --no-cuda-drivers --runtime openadkit --ros-distro "$ROS_DISTRO" \
  && pipx uninstall ansible \
  && /scripts/cleanup_apt.sh true

# =============================================================================
# Stage: common-devel
# Common development image with ROS and autoware-universe common packages
# =============================================================================
FROM common-base AS common-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Set up common environment
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  ./setup-dev-env.sh  -y --module all --no-nvidia --no-cuda-drivers --ros-distro "$ROS_DISTRO" openadkit  \
  && ./setup-dev-env.sh -y --module dev-tools --ros-distro "$ROS_DISTRO" openadkit  \
  && pipx uninstall ansible \
  && /scripts/cleanup_apt.sh \
  && echo "source /opt/ros/${ROS_DISTRO}/setup.bash" > /etc/bash.bashrc

# Install rosdep dependencies
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=bind,source=autoware/src/core,target=/autoware/src/core \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/common,target=/autoware/src/universe/autoware_universe/common \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/evaluator,target=/autoware/src/universe/autoware_universe/evaluator \
  --mount=type=bind,source=autoware/src/universe/external/eagleye,target=/autoware/src/universe/external/eagleye \
  --mount=type=bind,source=autoware/src/universe/external/glog,target=/autoware/src/universe/external/glog \
  --mount=type=bind,source=autoware/src/universe/external/llh_converter,target=/autoware/src/universe/external/llh_converter \
  --mount=type=bind,source=autoware/src/universe/external/managed_transform_buffer,target=/autoware/src/universe/external/managed_transform_buffer \
  --mount=type=bind,source=autoware/src/universe/external/morai_msgs,target=/autoware/src/universe/external/morai_msgs \
  --mount=type=bind,source=autoware/src/universe/external/muSSP,target=/autoware/src/universe/external/muSSP \
  --mount=type=bind,source=autoware/src/universe/external/pointcloud_to_laserscan,target=/autoware/src/universe/external/pointcloud_to_laserscan \
  --mount=type=bind,source=autoware/src/universe/external/rtklib_ros_bridge,target=/autoware/src/universe/external/rtklib_ros_bridge \
  --mount=type=bind,source=autoware/src/universe/external/tier4_autoware_msgs,target=/autoware/src/universe/external/tier4_autoware_msgs \
  --mount=type=bind,source=autoware/src/middleware/external,target=/autoware/src/middleware/external \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-universe-common-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-universe-common-pkgs.txt \
  && cat /tmp/rosdep-universe-common-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh

# Build autoware-universe common packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
  --mount=type=bind,source=autoware/src/core,target=/autoware/src/core \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/common,target=/autoware/src/universe/autoware_universe/common \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/evaluator,target=/autoware/src/universe/autoware_universe/evaluator \
  --mount=type=bind,source=autoware/src/universe/external/eagleye,target=/autoware/src/universe/external/eagleye \
  --mount=type=bind,source=autoware/src/universe/external/glog,target=/autoware/src/universe/external/glog \
  --mount=type=bind,source=autoware/src/universe/external/llh_converter,target=/autoware/src/universe/external/llh_converter \
  --mount=type=bind,source=autoware/src/universe/external/managed_transform_buffer,target=/autoware/src/universe/external/managed_transform_buffer \
  --mount=type=bind,source=autoware/src/universe/external/morai_msgs,target=/autoware/src/universe/external/morai_msgs \
  --mount=type=bind,source=autoware/src/universe/external/muSSP,target=/autoware/src/universe/external/muSSP \
  --mount=type=bind,source=autoware/src/universe/external/pointcloud_to_laserscan,target=/autoware/src/universe/external/pointcloud_to_laserscan \
  --mount=type=bind,source=autoware/src/universe/external/rtklib_ros_bridge,target=/autoware/src/universe/external/rtklib_ros_bridge \
  --mount=type=bind,source=autoware/src/universe/external/tier4_autoware_msgs,target=/autoware/src/universe/external/tier4_autoware_msgs \
  --mount=type=bind,source=autoware/src/middleware/external,target=/autoware/src/middleware/external \
  --mount=type=bind,source=/autoware/src/launcher,target=/autoware/src/launcher \
  source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && /scripts/build_and_clean.sh "${CCACHE_DIR}" /opt/autoware

# =============================================================================
# Stage: common-devel-cuda
# Common development image with CUDA support
# =============================================================================
FROM common-devel AS common-devel-cuda
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Set up development environment with CUDA support
RUN --mount=type=ssh \
  ./setup-dev-env.sh -y --module all --no-cuda-drivers --ros-distro "$ROS_DISTRO" openadkit  \
  && pipx uninstall ansible \
  && /scripts/cleanup_apt.sh true
