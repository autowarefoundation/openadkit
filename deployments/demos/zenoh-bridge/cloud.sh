#!/bin/bash

# Import common library
source ./common.sh

# Define Cloud services
CLOUD_SERVICES="visualizer cloud_zenoh_bridge"

run_compose "Cloud" "$CLOUD_SERVICES" "$@"
if [ "$1" == "up" ] || [ -z "$1" ]; then
    echo -e "${YELLOW}[Info]${NC} Cloud services started."
    echo -e "       To connect from Edge, set CLOUD_IP to one of the following:"
    
    # Function to get IPs excluding docker/br/veth interfaces
    get_ips() {
        ip -o -4 addr show | awk '
        $2 !~ /^(docker|br-|veth|lo$)/ {
            ip = $4; sub("/.*", "", ip);
            if (ip ~ /^140\.112\./) print "match_public " ip;
            else if (ip ~ /^192\.168\.|^10\.|^172\./) print "match_private " ip;
            else print "match_other " ip;
        }'
    }

    # Process and display IPs
    IPS=$(get_ips)
    
    if echo "$IPS" | grep -q "match_public"; then
        echo -e "\n       ${GREEN}[Public/WLAN IPs]${NC}"
        echo "$IPS" | grep "match_public" | cut -d' ' -f2 | sed 's/^/       - /'
    fi

    if echo "$IPS" | grep -q "match_private"; then
        echo -e "\n       ${YELLOW}[Private/LAN IPs]${NC}"
        echo "$IPS" | grep "match_private" | cut -d' ' -f2 | sed 's/^/       - /'
    fi
fi
