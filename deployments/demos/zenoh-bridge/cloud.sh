#!/bin/bash

# Import common library
source ./common.sh

# Define Cloud services
CLOUD_SERVICES="visualizer cloud_zenoh_bridge"

run_compose "Cloud" "$CLOUD_SERVICES" "$@"
