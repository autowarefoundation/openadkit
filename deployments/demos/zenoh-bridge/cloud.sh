#!/bin/bash

# Function to get IPs excluding docker/br/veth interfaces
get_ips() {
    ip -o -4 addr show | awk '
    $2 !~ /^(docker|br-|veth|lo$)/ {
        ip = $4; sub("/.*", "", ip);
        # RFC 1918 Private IP ranges
        if (ip ~ /^10\./ || ip ~ /^192\.168\./ || ip ~ /^172\.(1[6-9]|2[0-9]|3[0-1])\./) {
            print "match_private " ip;
        } else {
            # Assume everything else is Public/Routable
            print "match_public " ip;
        }
    }'
}

# Function to get Docker Internal IP of cloud_zenoh_bridge
get_docker_ip() {
    local container_id
    container_id=$(docker compose ps -q cloud_zenoh_bridge)
    
    if [ -z "$container_id" ]; then
        return
    fi

    # Use pure docker inspect with Go template (println adds newline for multiple IPs)
    docker inspect "$container_id" -f '{{range .NetworkSettings.Networks}}{{println .IPAddress}}{{end}}' 2>/dev/null
}

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

# Run Compose
run_compose "Cloud" "$TARGET_SERVICES" "$CMD" "${ARGS[@]}"

# Display Info only for 'up' or 'dry-run'
if [ "$CMD" == "up" ] || [ "$CMD" == "dry-run" ]; then
    if [ "$CMD" == "dry-run" ]; then
        echo -e "${YELLOW}[Info]${NC} Dry Run mode. Connection info below:"
    else
        echo -e "${YELLOW}[Info]${NC} Cloud services started."
    fi
    echo -e "       To connect from Edge, set CLOUD_IP to one of the following:"

    # Process and display IPs
    IPS=$(get_ips)
    DOCKER_IP=$(get_docker_ip)
    
    if echo "$IPS" | grep -q "match_public"; then
        echo -e "\n       ${GREEN}[Public/Routable IPs]${NC}"
        echo "$IPS" | grep "match_public" | cut -d' ' -f2 | sed 's/^/       - /'
    fi

    if echo "$IPS" | grep -q "match_private"; then
        echo -e "\n       ${YELLOW}[Private/LAN IPs]${NC}"
        echo "$IPS" | grep "match_private" | cut -d' ' -f2 | sed 's/^/       - /'
    fi

    if [ -n "$DOCKER_IP" ]; then
        echo -e "\n       ${YELLOW}[Docker Internal IPs]${NC}"
        echo "$DOCKER_IP" | sed 's/^/       - /'
    fi

    if [[ "$TARGET_SERVICES" == *"teleop"* ]]; then
        echo -e "\n       ${CYAN}[Teleop Control]${NC}"
        echo -e "       To control the vehicle manually:"
        echo -e "       $ docker compose exec teleop bash"
        echo -e "       $ ros2 run autoware_manual_control keyboard_control"
    fi
fi
