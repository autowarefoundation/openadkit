#!/bin/bash

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

# Initialize map volume if simulation is disabled
# This ensures autoware_map volume is populated from the scenario_simulator image
if [ "${SCENARIO_SIMULATION}" == "false" ] && [ "$CMD" == "up" ]; then
    echo -e "${YELLOW}[Info]${NC} Simulation disabled. Initialize map volume..."
    docker compose up --no-start scenario_simulator
fi

# Run Compose
run_compose "Edge" "$EDGE_SERVICES" "$CMD" "${ARGS[@]}"
