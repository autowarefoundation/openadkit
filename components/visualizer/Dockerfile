# Dockerfile - Builds visualizer image
ARG COMMON_BASE_IMAGE=ghcr.io/autowarefoundation/openadkit-common:base
ARG COMMON_DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common:devel
ARG ROS_DISTRO=humble

# =============================================================================
# Build stage: visualizer-devel
# =============================================================================
FROM $COMMON_DEVEL_IMAGE AS visualizer-devel
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Install rosdep dependencies and build packages
RUN --mount=type=cache,target="${CCACHE_DIR}" \
  --mount=type=bind,source=autoware/src/universe/autoware_universe/visualization,target=/autoware/src/universe/autoware_universe/visualization \
  apt-get update \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && rosdep update \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" --dependency-types=exec > /tmp/rosdep-visualizer-exec-pkgs.txt \
  && /scripts/resolve_rosdep_keys.sh /autoware/src "${ROS_DISTRO}" > /tmp/rosdep-visualizer-pkgs.txt \
  && cat /tmp/rosdep-visualizer-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && /scripts/cleanup_apt.sh true \
  && source /opt/ros/"$ROS_DISTRO"/setup.bash \
  && source /opt/autoware/setup.bash \
  && /scripts/build_and_clean.sh "${CCACHE_DIR}" /opt/autoware

# =============================================================================
# Runtime stage: visualizer
# =============================================================================
FROM $COMMON_BASE_IMAGE AS visualizer
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG ROS_DISTRO

# Copy rosdep dependency lists and binaries from devel stage
COPY --from=visualizer-devel /tmp/rosdep-universe-common-exec-pkgs.txt /tmp/rosdep-universe-common-exec-pkgs.txt
COPY --from=visualizer-devel /tmp/rosdep-visualizer-exec-pkgs.txt /tmp/rosdep-visualizer-exec-pkgs.txt

# Install rosdep dependencies and apt packages (openbox, VNC, and simulator dependencies)
RUN --mount=type=ssh \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  apt-get update \
  && cat /tmp/rosdep-universe-common-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && cat /tmp/rosdep-visualizer-exec-pkgs.txt | xargs apt-get install -y --no-install-recommends \
  && apt-get install -y --no-install-recommends \
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
  && pip install --no-cache-dir yamale xmlschema \
  && /scripts/cleanup_apt.sh true \
  && /scripts/cleanup_system.sh $ROS_DISTRO

# Copy binaries from devel stage
COPY --from=visualizer-devel /opt/autoware /opt/autoware

# Create SSL certificate for NoVNC
RUN openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout /etc/ssl/private/novnc.key \
  -out /etc/ssl/certs/novnc.crt \
  -days 365 \
  -subj "/O=Autoware-OpenADKit/CN=localhost"

# Need to expose VNC and NoVNC ports when running the container
EXPOSE 5900 6080

# Add source commands to bash startup
RUN echo "source /opt/ros/$ROS_DISTRO/setup.bash" >> /root/.bashrc && \
  echo "source /opt/autoware/setup.bash" >> /root/.bashrc

# Copy startup scripts
COPY components/visualizer/etc/xstartup /root/.vnc/xstartup
COPY components/visualizer/etc/visualizer_entrypoint.sh /scripts/visualizer_entrypoint.sh
RUN chmod +x /scripts/visualizer_entrypoint.sh && chmod +x /root/.vnc/xstartup
ENTRYPOINT ["/scripts/visualizer_entrypoint.sh"]
