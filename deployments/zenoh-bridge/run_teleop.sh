#!/bin/bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

# Check if teleop service is running
if ! docker compose --env-file "$SCRIPT_DIR/config.env" ps --services --filter "status=running" | grep -q "teleop"; then
    echo -e "\033[0;31m[Error]\033[0m Teleop service is not running."
    echo "Please start it first: ./cloud.sh up --with-teleop -d"
    exit 1
fi

echo -e "\033[1;33m[Teleop]\033[0m Terminal Mode"
echo "Connecting to container..."

# Execute interactive bash with environment sourced
docker compose --env-file "$SCRIPT_DIR/config.env" exec -it teleop bash -c "
    source /autoware_manual_control_ws/install/setup.bash && \
    echo -e '\n\033[1;32mStarting Keyboard Control...\033[0m' && \
    ros2 run autoware_manual_control keyboard_control --ros-args --params-file /autoware_manual_control_ws/teleop_config.yaml"
