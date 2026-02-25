#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(readlink -f "$(dirname "$0")")
WORKSPACE_ROOT="$SCRIPT_DIR"

# Function to print help message
print_help() {
    echo "Usage: build.sh [OPTIONS]"
    echo "Options:"
    echo "  -h | --help     Display this help message"
    echo "  --platform      Specify the platform (linux/amd64 or linux/arm64, default: current platform)"
    echo "  --ros-distro    Specify ROS distribution (humble or jazzy, default: humble)"
    echo "  --no-cuda       Do not build CUDA images (default: false)"
    echo "  --target        Specify the target images to build (common, components, universe, default: components)"
}

# Parse arguments
parse_arguments() {
    while [ "$1" != "" ]; do
        case "$1" in
        --help | -h)
            print_help
            exit 1
            ;;
        --no-cuda)
            option_no_cuda=true
            ;;
        --platform)
            option_platform="$2"
            shift
            ;;
        --target)
            option_target="$2"
            shift
            ;;
        --ros-distro)
            option_ros_distro="$2"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            print_help
            exit 1
            ;;
        esac
        shift
    done
}

# Set ROS distribution
set_ros_distro() {
    if [ -n "$option_ros_distro" ]; then
        ros_distro="$option_ros_distro"
    else
        ros_distro="humble"
    fi
}

# Set build options
set_build_options() {
    if [ -n "$option_target" ]; then
        target="$option_target"
    else
        target="components"
    fi
}

# Set platform
set_platform() {
    if [ -n "$option_platform" ]; then
        platform="$option_platform"
    else
        platform="linux/amd64"
        if [ "$(uname -m)" = "aarch64" ]; then
            platform="linux/arm64"
        fi
    fi
}

# Clone autoware repositories
clone_repositories() {
    cd "$WORKSPACE_ROOT"

    if [ ! -d "autoware" ]; then
        echo "Cloning Autoware repository..."
        git clone https://github.com/autowarefoundation/autoware.git autoware
    fi

    if [ ! -d "autoware/src" ]; then
        mkdir -p autoware/src
        vcs import autoware/src <autoware/repositories/autoware.repos
    else
        echo "Source directory already exists. Updating repositories..."
        vcs import autoware/src <autoware/repositories/autoware.repos
        vcs pull autoware/src
    fi
}

# Build images
build_images() {
    # https://github.com/docker/buildx/issues/484
    export BUILDKIT_STEP_LOG_MAX_SIZE=10000000

    local bake_file="$SCRIPT_DIR/components/docker-bake.hcl"
    local base_image="ros:${ros_distro}-ros-base-jammy"
    local image_common="openadkit-common"
    local image_component="openadkit"

    echo "Building images with:"
    echo "  Target: $target"
    echo "  Platform: $platform"
    echo "  ROS distro: $ros_distro"
    echo "  Base image: $base_image"
    echo "  CUDA: $([ "$option_no_cuda" = "true" ] && echo "disabled" || echo "enabled")"

    set -x

    # =========================================================================
    # Stage 1: Common images
    # =========================================================================
    docker buildx bake --allow=ssh --load --progress=plain -f "$bake_file" \
        --set "*.context=$WORKSPACE_ROOT" \
        --set "*.ssh=default" \
        --set "*.platform=$platform" \
        --set "*.args.ROS_DISTRO=$ros_distro" \
        --set "*.args.BASE_IMAGE=$base_image" \
        --set "common-base.tags=${image_common}:base" \
        --set "common-devel.tags=${image_common}:devel" \
        common-base common-devel

    if [ "$option_no_cuda" != "true" ]; then
        docker buildx bake --allow=ssh --load --progress=plain -f "$bake_file" \
            --set "*.context=$WORKSPACE_ROOT" \
            --set "*.ssh=default" \
            --set "*.platform=$platform" \
            --set "*.args.ROS_DISTRO=$ros_distro" \
            --set "*.args.BASE_IMAGE=$base_image" \
            --set "common-base-cuda.tags=${image_common}:base-cuda" \
            --set "common-devel-cuda.tags=${image_common}:devel-cuda" \
            common-base-cuda common-devel-cuda
    fi

    if [ "$target" = "common" ]; then
        set +x
        return
    fi

    # =========================================================================
    # Stage 2: Component images
    # =========================================================================
    docker buildx bake --allow=ssh --load --progress=plain -f "$bake_file" \
        --set "*.context=$WORKSPACE_ROOT" \
        --set "*.ssh=default" \
        --set "*.platform=$platform" \
        --set "*.args.ROS_DISTRO=$ros_distro" \
        --set "*.args.COMMON_BASE_IMAGE=${image_common}:base" \
        --set "*.args.COMMON_DEVEL_IMAGE=${image_common}:devel" \
        --set "sensing-perception.tags=${image_component}:sensing-perception" \
        --set "localization-mapping.tags=${image_component}:localization-mapping" \
        --set "planning-control.tags=${image_component}:planning-control" \
        --set "vehicle-system.tags=${image_component}:vehicle-system" \
        --set "api.tags=${image_component}:api" \
        --set "visualizer.tags=${image_component}:visualizer" \
        --set "simulator.tags=${image_component}:simulator" \
        sensing-perception localization-mapping planning-control vehicle-system api visualizer simulator

    if [ "$option_no_cuda" != "true" ]; then
        docker buildx bake --allow=ssh --load --progress=plain -f "$bake_file" \
            --set "*.context=$WORKSPACE_ROOT" \
            --set "*.ssh=default" \
            --set "*.platform=$platform" \
            --set "*.args.ROS_DISTRO=$ros_distro" \
            --set "*.args.COMMON_BASE_CUDA_IMAGE=${image_common}:base-cuda" \
            --set "*.args.COMMON_DEVEL_CUDA_IMAGE=${image_common}:devel-cuda" \
            --set "sensing-perception-cuda.tags=${image_component}:sensing-perception-cuda" \
            sensing-perception-cuda
    fi

    if [ "$target" = "components" ]; then
        set +x
        return
    fi

    # =========================================================================
    # Stage 3: Universe images
    # =========================================================================
    docker buildx bake --allow=ssh --load --progress=plain -f "$bake_file" \
        --set "*.context=$WORKSPACE_ROOT" \
        --set "*.ssh=default" \
        --set "*.platform=$platform" \
        --set "*.args.ROS_DISTRO=$ros_distro" \
        --set "*.args.COMMON_BASE_IMAGE=${image_common}:base" \
        --set "*.args.COMMON_DEVEL_IMAGE=${image_common}:devel" \
        --set "*.args.SENSING_PERCEPTION_IMAGE=${image_component}:sensing-perception" \
        --set "*.args.LOCALIZATION_MAPPING_IMAGE=${image_component}:localization-mapping" \
        --set "*.args.PLANNING_CONTROL_IMAGE=${image_component}:planning-control" \
        --set "*.args.VEHICLE_SYSTEM_IMAGE=${image_component}:vehicle-system" \
        --set "*.args.API_IMAGE=${image_component}:api" \
        --set "*.args.VISUALIZER_IMAGE=${image_component}:visualizer" \
        --set "*.args.SIMULATOR_IMAGE=${image_component}:simulator" \
        --set "universe.tags=${image_component}:universe" \
        universe

    if [ "$option_no_cuda" != "true" ]; then
        docker buildx bake --allow=ssh --load --progress=plain -f "$bake_file" \
            --set "*.context=$WORKSPACE_ROOT" \
            --set "*.ssh=default" \
            --set "*.platform=$platform" \
            --set "*.args.ROS_DISTRO=$ros_distro" \
            --set "*.args.COMMON_BASE_CUDA_IMAGE=${image_common}:base-cuda" \
            --set "*.args.COMMON_DEVEL_CUDA_IMAGE=${image_common}:devel-cuda" \
            --set "*.args.SENSING_PERCEPTION_CUDA_IMAGE=${image_component}:sensing-perception-cuda" \
            --set "*.args.LOCALIZATION_MAPPING_IMAGE=${image_component}:localization-mapping" \
            --set "*.args.PLANNING_CONTROL_IMAGE=${image_component}:planning-control" \
            --set "*.args.VEHICLE_SYSTEM_IMAGE=${image_component}:vehicle-system" \
            --set "*.args.API_IMAGE=${image_component}:api" \
            --set "*.args.VISUALIZER_IMAGE=${image_component}:visualizer" \
            --set "*.args.SIMULATOR_IMAGE=${image_component}:simulator" \
            --set "universe-cuda.tags=${image_component}:universe-cuda" \
            universe-cuda
    fi

    set +x
}

# Remove dangling images
remove_dangling_images() {
    docker image prune -f
}

# Main script execution
parse_arguments "$@"
set_ros_distro
set_build_options
set_platform
clone_repositories
build_images
remove_dangling_images
