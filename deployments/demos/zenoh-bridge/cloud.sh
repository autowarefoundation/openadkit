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

# Import common library
source ./common.sh

# Define Cloud services
CLOUD_SERVICES="visualizer cloud_zenoh_bridge"

run_compose "Cloud" "$CLOUD_SERVICES" "$@"
if [ "$1" == "up" ] || [ -z "$1" ] || [ "$1" == "dry-run" ]; then
    if [ "$1" == "dry-run" ]; then
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
fi
