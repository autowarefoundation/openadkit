#!/bin/bash
set -euo pipefail

# Function to show help message
show_help() {
    echo "Usage: ./cloud.sh [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  up              Start Cloud services (default)"
    echo "  down            Stop and remove Cloud services"
    echo "  ps              List status of Cloud services"
    echo "  logs            View logs of Cloud services"
    echo "  config          Validate and view the Compose file"
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
source ./common.sh

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

# Compose reads .env itself. Read only the effective bind value for this
# preflight, without sourcing the file or overriding exported variables.
if ! ZENOH_BIND_IP=$(read_dotenv_value ZENOH_ROUTER_BIND_IP); then
    ZENOH_BIND_IP=127.0.0.1
fi
if [[ "$CMD" == "up" || "$CMD" == "dry-run" ]] \
    && [[ "$ZENOH_BIND_IP" == "0.0.0.0" || "$ZENOH_BIND_IP" == "::" ]]; then
    echo -e "${RED}[Error]${NC} Refusing wildcard Zenoh binding ${ZENOH_BIND_IP}."
    echo "        Bind ZENOH_ROUTER_BIND_IP to an exact VPN/private-interface address."
    echo "        Zenoh TCP port 7448 has no transport authentication or encryption."
    exit 1
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
    if [[ "$ZENOH_BIND_IP" == "127.0.0.1" || "$ZENOH_BIND_IP" == "::1" ]]; then
        echo "       Zenoh remains loopback-only for this single-host deployment."
    else
        echo "       Zenoh is bound to ${ZENOH_BIND_IP}."
        echo "       On Edge, set CLOUD_IP=${ZENOH_BIND_IP} and connect only over the VPN/private network."
        echo "       TCP 7448 is not authenticated or encrypted; restrict it to trusted VPN peers."
    fi

    if [[ "$TARGET_SERVICES" == *"teleop"* ]]; then
        echo -e "\n       ${CYAN}[Teleop Control]${NC}"
        echo -e "       To control the vehicle manually:"
        echo -e "       $ docker compose exec teleop bash"
        echo -e "       $ ros2 run autoware_manual_control keyboard_control"
    fi
fi
