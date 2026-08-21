#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

# Function to show help message
show_help() {
    echo "Usage: ./cloud.sh [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  up              Start Cloud services (default)"
    echo "  down            Stop and remove Cloud services"
    echo "  ps              List status of Cloud services"
    echo "  logs            View logs of Cloud services"
    echo "  config          Validate the Compose file"
    echo "  dry-run         Show what would be executed without doing it"
    echo ""
    echo "Options:"
    echo "  -h, --help      Show this help message"
    echo "  --with-teleop   Include Teleop service (Manual Control)"
    echo "  --build         Build images before starting containers"
    echo ""
    echo "Examples:"
    echo "  ./cloud.sh up --with-teleop"
    echo "  ./cloud.sh down"
}

# Import common library
source "$SCRIPT_DIR/common.sh"

# Define Cloud services
BASE_SERVICES="visualizer cloud_zenoh_bridge"
TARGET_SERVICES="$BASE_SERVICES"

# Argument parsing
CMD=""
ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        --with-teleop)
            TARGET_SERVICES="$TARGET_SERVICES teleop"
            shift
            ;;
        up|down|ps|logs|config|dry-run)
            CMD="$1"
            shift
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

# Default command is 'up' if not specified
if [ -z "$CMD" ]; then
    CMD="up"
fi

# Teardown must remove everything the cloud side owns — including the one-shot
# readiness helper and teleop — regardless of which optional services
# `up` started, so `down` cannot leave orphaned containers behind.
if [ "$CMD" == "down" ]; then
    TARGET_SERVICES="visualizer cloud_zenoh_bridge cloud_zenoh_ready teleop"
fi

# Run Compose
run_compose "Cloud" "$TARGET_SERVICES" "$CMD" "${ARGS[@]}"

# Display Info only for 'up' or 'dry-run'
if [ "$CMD" == "up" ] || [ "$CMD" == "dry-run" ]; then
    if [ "$CMD" == "dry-run" ]; then
        echo -e "${YELLOW}[Info]${NC} Dry Run mode. Connection info below:"
    else
        echo -e "${YELLOW}[Info]${NC} Cloud services started."
    fi
    echo "       Zenoh transport is internal to the Compose project."

    if [[ "$TARGET_SERVICES" == *"teleop"* ]]; then
        echo -e "\n       ${CYAN}[Teleop Control]${NC}"
        echo -e "       To control the vehicle manually:"
        echo -e "       $ ./run_teleop.sh"
    fi
fi
