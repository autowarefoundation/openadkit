#!/bin/bash
set -euo pipefail

# Function to show help message
show_help() {
    echo "Usage: ./edge.sh [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  up              Start Edge services (default)"
    echo "  down            Stop and remove Edge services"
    echo "  ps              List status of Edge services"
    echo "  logs            View logs of Edge services"
    echo "  config          Validate and view the Compose file"
    echo "  dry-run         Show what would be executed without doing it"
    echo ""
    echo "Options:"
    echo "  -h, --help      Show this help message"
    echo "  --no-sim        Disable Scenario Simulator (only run Autoware & Bridge)"
    echo "  --build         Build images before starting containers"
}

# Import common library
source ./common.sh

# Define Edge services
EDGE_SERVICES="autoware scenario_simulator edge_zenoh_bridge"

# Argument parsing
CMD=""
ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        --no-sim)
            export SCENARIO_SIMULATION="false"
            # Remove scenario_simulator from EDGE_SERVICES
            EDGE_SERVICES="${EDGE_SERVICES/scenario_simulator/}"
            # Clean up extra spaces if any
            EDGE_SERVICES=$(echo "$EDGE_SERVICES" | xargs)
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

# Export default if not set
export SCENARIO_SIMULATION="${SCENARIO_SIMULATION:-true}"

# Default command is 'up' if not specified
if [ -z "$CMD" ]; then
    CMD="up"
fi

TARGET_SERVICES="$EDGE_SERVICES"

# The map is mounted from the host. Compose reads .env directly; this narrow
# parser obtains the same preflight value without executing dotenv as shell.
if ! MAP_DIR=$(read_dotenv_value MAP_PATH); then
    MAP_DIR="\$HOME/autoware_map/kashiwanoha_map"
fi
case "$MAP_DIR" in
    "\$HOME"/*) MAP_DIR="${HOME}${MAP_DIR#\$HOME}" ;;
    "\${HOME}"/*) MAP_DIR="${HOME}${MAP_DIR#\$\{HOME\}}" ;;
esac
if [[ -z "$MAP_DIR" ]]; then
    echo -e "${RED}[Error]${NC} MAP_PATH is empty. Set it in the environment or .env."
    exit 1
fi
if [ "$CMD" == "up" ]; then
    for map_file in lanelet2_map.osm pointcloud_map.pcd; do
        if [ ! -f "${MAP_DIR}/${map_file}" ]; then
            echo -e "${RED}[Error]${NC} Map file ${map_file} not found in ${MAP_DIR}."
            if [ -f ./install.sh ]; then
                echo -e "       Run ./install.sh sample-data zenoh-bridge --force to (re-)fetch the map."
            else
                echo -e "       Run ../../install.sh sample-data zenoh-bridge --force to (re-)fetch the map."
            fi
            exit 1
        fi
    done
fi

# Run Compose
run_compose "Edge" "$TARGET_SERVICES" "$CMD" "${ARGS[@]}"
