#!/usr/bin/env bash
# cspell:ignore openbox, VNC, tigervnc, novnc, websockify, newkey, xstartup, pixelformat, AUTHTOKEN, authtoken, vncserver, autoconnect, vncpasswd
# shellcheck disable=SC1090,SC1091
set -euo pipefail

cleanup() {
    echo "Shutting down VNC and websockify..."
    pkill websockify 2>/dev/null || true
    vncserver -kill :99 2>/dev/null || true
}
trap cleanup EXIT SIGTERM SIGINT

# Check if RVIZ_CONFIG is provided
if [ -z "${RVIZ_CONFIG:-}" ]; then
    echo -e "\e[31mRVIZ_CONFIG is not set defaulting to /opt/autoware/autoware_launch/share/autoware_launch/rviz/autoware.rviz\e[0m"
    RVIZ_CONFIG="/opt/autoware/autoware_launch/share/autoware_launch/rviz/autoware.rviz"
    export RVIZ_CONFIG
fi

if [ -z "${USE_SIM_TIME:-}" ]; then
    echo -e "\e[31mUSE_SIM_TIME is not set defaulting to false\e[0m"
    USE_SIM_TIME="false"
    export USE_SIM_TIME
fi

configure_vnc() {
    # Create Openbox application configuration
    mkdir -p /etc/xdg/openbox
    cat >/etc/xdg/openbox/rc.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc"
                xmlns:xi="http://www.w3.org/2001/XInclude">
  <applications>
    <application name="rviz2">
      <maximized>yes</maximized>
      <position force="yes">
        <x>center</x>
        <y>center</y>
      </position>
      <focus>yes</focus>
      <desktop>1</desktop>
    </application>
  </applications>
</openbox_config>
EOF
    # Create rviz2 start script
    cat >/usr/local/bin/start-rviz2.sh <<'EOF'
#!/bin/bash
source /opt/ros/"$ROS_DISTRO"/setup.bash
source /opt/autoware/setup.bash

# Optional GPU-accelerated rendering via VirtualGL (EGL). RViz renders in
# software (llvmpipe) by default, which is slow for dense point clouds and
# camera images. When an NVIDIA GPU is available in the container, render on
# it instead. Detection is at runtime so the same image works with or without
# a GPU. Override with RVIZ_GPU=on (force) or RVIZ_GPU=off (disable).
RVIZ_GPU="${RVIZ_GPU:-auto}"
rviz_launcher=""
if [ "$RVIZ_GPU" != "off" ]; then
    if [ "$RVIZ_GPU" = "on" ] || { [ -e /dev/nvidia0 ] && command -v vglrun >/dev/null 2>&1 && ldconfig -p 2>/dev/null | grep -q libEGL_nvidia; }; then
        rviz_launcher="vglrun -d egl"
        echo "RViz: GPU-accelerated rendering via VirtualGL (EGL)"
    fi
fi
[ -z "$rviz_launcher" ] && echo "RViz: software rendering (no GPU detected; set RVIZ_GPU=on to force VirtualGL)"

exec $rviz_launcher rviz2 -d "$RVIZ_CONFIG" --ros-args -p use_sim_time:="$USE_SIM_TIME"
EOF
    chmod +x /usr/local/bin/start-rviz2.sh
    echo "/usr/local/bin/start-rviz2.sh" >>/etc/xdg/openbox/autostart

    # Configure VNC password
    if [ -z "${REMOTE_PASSWORD:-}" ]; then
        echo -e "\e[31mREMOTE_PASSWORD is not set. Please set it before starting.\e[0m"
        exit 1
    fi
    mkdir -p ~/.vnc
    echo "$REMOTE_PASSWORD" | vncpasswd -f >~/.vnc/passwd && chmod 600 ~/.vnc/passwd

    # Start VNC server with Openbox. -localhost restricts the raw VNC port
    # (5999) to loopback so only websockify (which connects to localhost:5999
    # inside the container) can reach it. This is important under
    # network_mode: host where the container's loopback == the host's.
    echo "Starting VNC server with Openbox..."
    if ! vncserver :99 -localhost -geometry 1024x768 -depth 16 -pixelformat rgb565; then
        echo "Failed to start VNC server"
        exit 1
    fi

    # Set the DISPLAY variable to match VNC server
    echo "Setting DISPLAY to :99"
    echo "export DISPLAY=:99" >>~/.bashrc
    sleep 2

    # Generate a unique self-signed TLS certificate at runtime so each
    # container instance has its own key pair (instead of a shared build-time
    # certificate baked into the image).
    echo "Generating TLS certificate for NoVNC..."
    mkdir -p /etc/ssl/private /etc/ssl/certs
    if ! openssl req -x509 -nodes -newkey rsa:2048 \
      -keyout /etc/ssl/private/novnc.key \
      -out /etc/ssl/certs/novnc.crt \
      -days 365 \
      -subj "/O=Autoware-OpenADKit/CN=localhost" >/dev/null 2>&1; then
        echo "Failed to generate TLS certificate for NoVNC"
        exit 1
    fi

    # Start NoVNC. Under network_mode: host (base deployments) bind to
    # loopback so noVNC is not exposed on every interface. Under bridge
    # networking (zenoh-bridge) set WEBSOCKIFY_BIND=0.0.0.0 so Docker's port
    # forwarding can reach websockify from the bridge interface; the host-side
    # port mapping (127.0.0.1:6081:6080) still restricts external access to
    # loopback. The VNC server is always loopback-only (see -localhost above).
    echo "Starting NoVNC..."
    local websck_bind="${WEBSOCKIFY_BIND:-127.0.0.1}"
    if ! websockify --daemon --web=/usr/share/novnc/ \
      --cert=/etc/ssl/certs/novnc.crt --key=/etc/ssl/private/novnc.key \
      "${websck_bind}:6080" localhost:5999; then
        echo "Failed to start websockify (NoVNC server)"
        exit 1
    fi

    # Print info
    echo -e "\033[32m-------------------------------------------------------------------------\033[0m"
    echo -e "\033[32mBrowser interface available at https://127.0.0.1:6080/vnc.html?resize=scale&autoconnect=true\033[0m"
    echo -e "\033[32mUse the REMOTE_PASSWORD configured in your env file.\033[0m"
    echo -e "\033[32mThe websockify server is bound to ${websck_bind}.\033[0m"
    echo -e "\033[32m-------------------------------------------------------------------------\033[0m"
}

# Source ROS and Autoware setup files
: "${ROS_DISTRO:?ROS_DISTRO must be set (e.g. humble)}"
set +u
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "/opt/autoware/setup.bash"
set -u

# Execute passed command if provided, otherwise launch rviz2
if [ "${REMOTE_DISPLAY:-true}" == "false" ]; then
    echo "Launching local rviz2 display"
    [ $# -eq 0 ] && rviz2 -d "$RVIZ_CONFIG" --ros-args -p use_sim_time:="$USE_SIM_TIME"
    exec "$@"
else
    echo "Launching remote rviz2 display"
    configure_vnc
    [ $# -eq 0 ] && sleep infinity
    exec "$@"
fi
