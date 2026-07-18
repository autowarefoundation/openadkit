#!/usr/bin/env bash
# cspell:ignore openbox, VNC, tigervnc, novnc, websockify, newkey, xstartup, pixelformat, AUTHTOKEN, authtoken, vncserver, autoconnect, vncpasswd
# shellcheck disable=SC1090,SC1091
set -euo pipefail

VNC_PID=""
WEBSOCKIFY_PID=""
COMMAND_PID=""

if [ "$(id -u)" -eq 0 ]; then
    echo "Visualizer must run as a non-root user" >&2
    exit 1
fi

terminate_child() {
    local pid="${1:-}"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 0
    kill -TERM "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
}

cleanup() {
    trap - EXIT INT TERM
    echo "Shutting down VNC and websockify..."
    terminate_child "$COMMAND_PID"
    terminate_child "$WEBSOCKIFY_PID"
    terminate_child "$VNC_PID"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

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
    mkdir -p "$HOME/.config/openbox" "$HOME/.local/bin"
    cat >"$HOME/.config/openbox/rc.xml" <<'EOF'
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
    cat >"$HOME/.local/bin/start-rviz2.sh" <<'EOF'
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
    chmod +x "$HOME/.local/bin/start-rviz2.sh"
    grep -qxF "$HOME/.local/bin/start-rviz2.sh" "$HOME/.config/openbox/autostart" \
        || echo "$HOME/.local/bin/start-rviz2.sh" >>"$HOME/.config/openbox/autostart"

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
    vncserver :99 -fg -localhost -geometry 1024x768 -depth 16 -pixelformat rgb565 &
    VNC_PID=$!
    sleep 2
    if ! kill -0 "$VNC_PID" 2>/dev/null; then
        wait "$VNC_PID" 2>/dev/null || true
        VNC_PID=""
        echo "Failed to start VNC server"
        return 1
    fi

    # Set the DISPLAY variable to match VNC server
    echo "Setting DISPLAY to :99"
    grep -qxF "export DISPLAY=:99" ~/.bashrc || echo "export DISPLAY=:99" >>~/.bashrc
    # Generate a unique self-signed TLS certificate at runtime so each
    # container instance has its own key pair (instead of a shared build-time
    # certificate baked into the image).
    echo "Generating TLS certificate for NoVNC..."
    mkdir -p "$HOME/.vnc"
    if ! openssl req -x509 -nodes -newkey rsa:2048 \
      -keyout "$HOME/.vnc/novnc.key" \
      -out "$HOME/.vnc/novnc.crt" \
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
    websockify --web=/usr/share/novnc/ \
      --cert="$HOME/.vnc/novnc.crt" --key="$HOME/.vnc/novnc.key" \
      "${websck_bind}:6080" localhost:5999 &
    WEBSOCKIFY_PID=$!
    sleep 1
    if ! kill -0 "$WEBSOCKIFY_PID" 2>/dev/null; then
        wait "$WEBSOCKIFY_PID" 2>/dev/null || true
        WEBSOCKIFY_PID=""
        echo "Failed to start websockify (NoVNC server)"
        return 1
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
    if [ $# -eq 0 ]; then
        sleep infinity
    else
        "$@" &
        COMMAND_PID=$!
        command_status=0
        wait "$COMMAND_PID" || command_status=$?
        COMMAND_PID=""
        exit "$command_status"
    fi
fi
