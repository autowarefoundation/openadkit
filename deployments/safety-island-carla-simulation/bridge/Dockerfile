# cspell:ignore openbox, VNC, tigervnc, novnc, websockify, newkey, xstartup, keyout
FROM ghcr.io/autowarefoundation/autoware:universe-20250207@sha256:5482c148addbd13c005e86452fc9c40502a8c87759f679b8b61d83943059ada7 AS safety-island-bridge
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO
ENV ROS_DISTRO=${ROS_DISTRO}
WORKDIR /autoware

# Fix expired ROS GPG key issue comprehensively
# See: https://github.com/osrf/docker_images/issues/535
RUN apt-get update --allow-unauthenticated || true && \
    apt-get install -y --allow-unauthenticated curl gnupg2 && \
    apt-key del F42ED6FBAB17C654 || true && \
    curl -s https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc | apt-key add - && \
    curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /tmp/ros.key && \
    cat /tmp/ros.key | gpg --dearmor --batch --yes -o /usr/share/keyrings/ros2-latest-archive-keyring.gpg && \
    rm /tmp/ros.key

# Install domain bridge
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y ros-$ROS_DISTRO-domain-bridge

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
