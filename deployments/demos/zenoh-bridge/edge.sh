#!/bin/bash

# Import common library
source ./common.sh

# Define Edge services
EDGE_SERVICES="autoware scenario_simulator edge_zenoh_bridge"

run_compose "Edge" "$EDGE_SERVICES" "$@"
