#!/bin/bash
# =============================================================================
# autoware_entrypoint.sh
# =============================================================================
# This script is the entrypoint for the autoware container.
# It sources the ROS 2 and autoware setup.bash files and executes the provided command.
# =============================================================================
set -e

# Required environment variables
: "${ROS_DISTRO:?ROS_DISTRO is required}"
# Set default RMW implementation if not provided
if [ -z "${RMW_IMPLEMENTATION}" ]; then
    export RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"
    echo "RMW_IMPLEMENTATION not set. Using default: rmw_cyclonedds_cpp"
fi

# Debug information
echo "ROS_DISTRO: $ROS_DISTRO"
echo "RMW_IMPLEMENTATION: $RMW_IMPLEMENTATION"

# Source
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source /opt/autoware/setup.bash

# Execute command or start bash if no command is provided
if [[ $# -eq 0 ]]; then
    echo "No command provided. Starting bash..."
    exec /bin/bash
else
    echo "Executing command: $*"
    exec "$@"
fi
