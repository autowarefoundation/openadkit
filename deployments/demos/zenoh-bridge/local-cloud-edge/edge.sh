#!/bin/bash
# edge.sh

# Import common library
source ./common.sh

# Define Edge services (based on yaml content)
EDGE_SERVICES="autoware scenario_simulator edge_zenoh_bridge"

# Call common function
# Arg 1: Display Name
# Arg 2: Service List
# Arg 3+: User arguments
run_compose "Edge" "$EDGE_SERVICES" "$@"
