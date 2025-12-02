#!/bin/bash
# cloud.sh

# Import common library
source ./common.sh

# Define Cloud services
# Only keeping visualizer and cloud_zenoh_bridge
CLOUD_SERVICES="visualizer cloud_zenoh_bridge"

run_compose "Cloud" "$CLOUD_SERVICES" "$@"
