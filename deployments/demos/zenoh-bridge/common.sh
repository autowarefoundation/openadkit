#!/bin/bash

# Color definitions
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

run_compose() {
    local context_name="$1"
    shift
    local target_services="$1"
    shift

    # Read the command passed by the user. If not provided, default to "up".
    # Using parameter expansion to separate command and arguments.
    local cmd="${1:-up}"
    shift
    local args="$@"
    
    echo -e "${YELLOW}[${context_name}]${NC} Target Services: ${GREEN}${target_services}${NC}"

    # Logic handling
    case "$cmd" in
        "up")
            # If user inputs only 'up' or nothing (default), we might want to add -d, 
            # but here we respect user arguments.
            echo -e "${YELLOW}[${context_name}]${NC} Starting services..."
            docker compose up $args $target_services
            ;;
            
        "down")
            # Special handling: 'docker compose down' removes the entire network, affecting the other side.
            # Here we use 'stop' + 'rm -v' to remove specific services, simulating 'down' effect.
            echo -e "${RED}[${context_name}]${NC} Stopping and removing services (with volumes)..."
            docker compose stop $target_services
            docker compose rm -f -v $target_services
            ;;
            
        "dry-run")
            echo -e "${YELLOW}[${context_name}]${NC} [Dry Run] Would start services: ${GREEN}${target_services}${NC}"
            echo -e "${YELLOW}[${context_name}]${NC} Validating compose configuration..."
            docker compose config
            ;;

        *)
            # Pass through other commands (e.g., start, stop, restart, logs, pull, ps)
            echo -e "${YELLOW}[${context_name}]${NC} Executing: docker compose $cmd $args ..."
            docker compose $cmd${args:+ $args} $target_services
            ;;
    esac
}
