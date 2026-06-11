# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom,UndefinedVar
ARG UNIVERSE_COMMON_DEVEL_IMAGE
ARG UNIVERSE_COMMON_IMAGE

# =============================================================================
# Build stage: visualizer-devel
# =============================================================================
FROM ${UNIVERSE_COMMON_DEVEL_IMAGE} AS visualizer-devel
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
        /tmp/autoware/src/universe/autoware_universe/visualization \
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
# Runtime stage: visualizer
# =============================================================================
FROM ${UNIVERSE_COMMON_IMAGE} AS visualizer
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

USER root
COPY --from=visualizer-devel /opt/autoware /opt/autoware
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

# Install VNC / NoVNC / Openbox stack and simulation tooling.
USER root
RUN --mount=type=cache,id=apt-cache-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      curl \
      unzip \
      openbox \
      tigervnc-standalone-server \
      tigervnc-common \
      tigervnc-tools \
      novnc \
      websockify \
      python3-numpy \
      python3-xdg \
      pipx && \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install yamale && \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install xmlschema

# Create SSL certificate for NoVNC.
RUN openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout /etc/ssl/private/novnc.key \
    -out /etc/ssl/certs/novnc.crt \
    -days 365 \
    -subj "/O=Autoware-OpenADKit/CN=localhost"

# Need to expose VNC and NoVNC ports when running the container.
EXPOSE 5900 6080

# Add source commands to bash startup.
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc && \
    echo "source /opt/autoware/setup.bash" >> /root/.bashrc

# Copy startup scripts.
COPY components/visualizer/etc/xstartup /root/.vnc/xstartup
COPY components/visualizer/etc/visualizer_entrypoint.sh /usr/local/bin/visualizer_entrypoint.sh
RUN chmod +x /usr/local/bin/visualizer_entrypoint.sh /root/.vnc/xstartup

ENTRYPOINT ["/usr/local/bin/visualizer_entrypoint.sh"]
