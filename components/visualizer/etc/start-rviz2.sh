#!/bin/bash
export DISPLAY=:99
export VGL_DISPLAY=egl

source /opt/ros/"$ROS_DISTRO"/setup.bash
source /opt/autoware/setup.bash

RVIZ_GPU="${RVIZ_GPU:-auto}"
rviz_launcher=""
if [ "$RVIZ_GPU" != "off" ]; then
    vglrun_bin=""
    if command -v vglrun >/dev/null 2>&1; then
        vglrun_bin="$(command -v vglrun)"
    elif [ -x /opt/VirtualGL/bin/vglrun ]; then
        vglrun_bin=/opt/VirtualGL/bin/vglrun
    fi

    if [ "$RVIZ_GPU" = "on" ]; then
        if [ ! -e /dev/nvidia0 ] || [ -z "$vglrun_bin" ]; then
            echo "RViz: GPU rendering requested but NVIDIA device or VirtualGL is unavailable" >&2
            exit 1
        fi
        rviz_launcher="$vglrun_bin -d egl"
        echo "RViz: GPU-accelerated rendering forced via VirtualGL (EGL)"
    elif [ -e /dev/nvidia0 ] && [ -n "$vglrun_bin" ] && ldconfig -p 2>/dev/null | grep -Eq 'libEGL_nvidia|libGLX_nvidia'; then
        rviz_launcher="$vglrun_bin -d egl"
        echo "RViz: GPU-accelerated rendering via VirtualGL (EGL)"
    fi
fi
[ -z "$rviz_launcher" ] && echo "RViz: software rendering (no GPU detected; set RVIZ_GPU=on to force VirtualGL)"

exec $rviz_launcher rviz2 -d "$RVIZ_CONFIG" --ros-args -p use_sim_time:="$USE_SIM_TIME"
