#!/bin/bash
# shellcheck disable=SC1090,SC1091

# Parse parameters if not given using default values
parse_params() {
    RUN_MODE=${RUN_MODE:-planning-simulator}
    MAP_PATH=${MAP_PATH:-/root/autoware_map}
    SENSOR_MODEL=${SENSOR_MODEL:-sample_sensor_kit}
    VEHICLE_MODEL=${VEHICLE_MODEL:-sample_vehicle}
    SCENARIO_SIMULATION=${SCENARIO_SIMULATION:-false}
    USE_SIM_TIME=${USE_SIM_TIME:-false}
    RVIZ=${RVIZ:-false}
}

# Launch plain autoware
launch_autoware() {
    echo -e "\e[32mLaunching Autoware...\e[0m"

    ros2 launch autoware_launch autoware.launch.xml \
        map_path:="$MAP_PATH" \
        sensor_model:="$SENSOR_MODEL" \
        vehicle_model:="$VEHICLE_MODEL" \
        use_sim_time:="$USE_SIM_TIME" \
        rviz:="$RVIZ"
}

# Launch autoware in planning simulator mode
launch_planning_simulator() {
    echo -e "\e[32mLaunching Autoware in Planning Simulator mode...\e[0m"

    ros2 launch autoware_launch planning_simulator.launch.xml \
        map_path:="$MAP_PATH" \
        sensor_model:="$SENSOR_MODEL" \
        vehicle_model:="$VEHICLE_MODEL" \
        scenario_simulation:="$SCENARIO_SIMULATION" \
        use_sim_time:="$USE_SIM_TIME" \
        rviz:="$RVIZ"
}

# Set up environment variables
source "/opt/ros/$ROS_DISTRO/setup.bash"
source "/opt/autoware/setup.bash"

parse_params
if [ $# -gt 0 ]; then
    exec "$@"
else
    if [ "$RUN_MODE" == "planning-simulator" ]; then
        launch_planning_simulator
    else
        launch_autoware
    fi
fi