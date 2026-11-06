ARG SIMULATOR_IMAGE=ghcr.io/autowarefoundation/openadkit:simulator-humble
FROM ${SIMULATOR_IMAGE} AS carla-interface

ARG ROS_DISTRO=humble
ARG CARLA_PYTHON_VERSION=0.9.16

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    python3-pip \
    ros-${ROS_DISTRO}-compressed-image-transport \
    ros-${ROS_DISTRO}-topic-tools \
  && PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --no-cache-dir \
    carla==${CARLA_PYTHON_VERSION} \
    transforms3d \
  && rm -rf /var/lib/apt/lists/*
