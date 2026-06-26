#!/usr/bin/env bash
set -euo pipefail

CLR_GREEN="\033[32m"
CLR_RED="\033[31m"
CLR_YELLOW="\033[33m"
CLR_RESET="\033[0m"

INSTALL_NVIDIA=true
DOWNLOAD_ARTIFACTS=false
INSTALL_BUILD_DEPS=false
DOWNLOAD_SAMPLES=false
RUN_VERIFY=false

# Resolve the real invoking user whether the script is run via sudo or directly.
TARGET_USER="${SUDO_USER:-$(id -un)}"
USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

#### Functions ####
print_help() {
    cat <<EOF
Install Open AD Kit host dependencies and sample data.

Usage:
  install.sh [OPTIONS]
  install.sh sample-data [DEPLOYMENT] [OPTIONS]

Default behavior installs host dependencies (Docker and NVIDIA Container Toolkit).

Commands:
  sample-data            Download sample maps/rosbags only; defaults to all sample data

Deployments for sample-data:
  planning-simulation    Download the planning simulation map
  logging-simulation     Download the logging simulation map and rosbag
  scenario-simulation    Download the Kashiwanoha scenario map
  zenoh-bridge           Download the Kashiwanoha scenario map
  carla-simulation       No-op; CARLA assets are handled by its launcher
  all                    Download all non-CARLA sample data (default)

Options:
  --help                  Display this help message
  -h                      Display this help message
  --no-nvidia             Skip installation of NVIDIA container toolkit
  --download-artifacts    Download Autoware artifacts (does not skip Docker)
  --build-deps            Install tools needed to build images from source
                           (jq, vcs2l, python3-yaml, unzip, pipx, git)
  --download-samples      Download sample map/rosbag data for deployments
  --verify                Run post-install smoke tests (Docker + GPU if available)
  --force                 Re-download sample data in sample-data mode

Examples:
  # Install Docker + NVIDIA toolkit (default)
  curl -fsSL .../install.sh | sudo bash

  # Install Docker only (no NVIDIA)
  curl -fsSL .../install.sh | sudo bash -s -- --no-nvidia

  # Download artifacts + install Docker
  curl -fsSL .../install.sh | sudo bash -s -- --download-artifacts

  # Full developer environment: Docker + NVIDIA + build deps + samples + verify
  curl -fsSL .../install.sh | sudo bash -s -- --build-deps --download-samples --verify

  # Download all sample data without host setup
  ./install.sh sample-data

  # Re-download data for one deployment
  ./install.sh sample-data planning-simulation --force
EOF
}

log_info()  { echo -e "${CLR_GREEN}[INFO]${CLR_RESET} $*"; }
log_warn()  { echo -e "${CLR_YELLOW}[WARN]${CLR_RESET} $*"; }
log_error() { echo -e "${CLR_RED}[ERROR]${CLR_RESET} $*"; }

require_sudo() {
    if [[ $EUID -eq 0 ]]; then
        return 0
    fi

    if [[ -t 0 ]]; then
        sudo -v
    elif ! sudo -n true 2>/dev/null; then
        log_error "This script requires sudo privileges."
        echo "Please run with a user that has sudo access, e.g.:"
        echo "  curl -fsSL .../install.sh | sudo bash"
        exit 1
    fi
}

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "/etc/os-release not found. This script only supports Ubuntu."
        exit 1
    fi

    # shellcheck source=/dev/null
    . /etc/os-release

    if [[ "${ID:-}" != "ubuntu" ]]; then
        log_error "Unsupported OS: '${ID:-unknown}'. This script only supports Ubuntu."
        exit 1
    fi

    if [[ "${VERSION_ID:-}" != "22.04" ]]; then
        log_warn "Untested Ubuntu version: ${VERSION_ID:-unknown}. Validated on 22.04 (Jammy). Continuing anyway."
    fi
}

install_nvidia_container_toolkit() {
    log_info "Installing NVIDIA Container Toolkit..."

    # Remove any pre-existing repo configuration to avoid duplicate entries
    sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit*.list
    sudo rm -f /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

    sudo apt-get update
    sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg2

    # Add NVIDIA GPG key and repository (dearmored per official NVIDIA docs)
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | sudo gpg --dearmor \
        -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit

    # Register NVIDIA runtime with Docker and restart
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker

    log_info "NVIDIA Container Toolkit installed successfully."
}

install_docker() {
    if command -v docker &>/dev/null; then
        log_info "Docker is already installed ($(docker --version)). Skipping."
        return
    fi

    log_info "Installing Docker..."

    # Remove conflicting packages (Docker official install guide step)
    for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
        sudo apt-get remove -y "$pkg" 2>/dev/null || true
    done

    sudo apt-get update
    sudo apt-get install -y ca-certificates curl

    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    # Add repository
    echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    # Add target user to docker group
    sudo groupadd docker 2>/dev/null || true
    sudo usermod -aG docker "$TARGET_USER"

    # Ensure Docker starts on boot
    sudo systemctl enable --now docker

    log_info "Docker installed successfully."
}

install_build_dependencies() {
    log_info "Installing build dependencies (jq, pipx, vcs2l, python3-yaml, unzip, git)..."

    sudo apt-get update
    sudo apt-get install -y jq python3-yaml unzip git pipx

    # Install vcs2l via pipx as the target user (not root), because pipx
    # drops packages into the user's home directory.
    sudo -u "$TARGET_USER" pipx install --force vcs2l

    # Ensure pipx binaries are on PATH in this shell invocation
    PIPX_BIN_DIR="${USER_HOME}/.local/bin"
    sudo -u "$TARGET_USER" python3 -m pipx ensurepath
    case ":${PATH}:" in
        *":${PIPX_BIN_DIR}:") ;;
        *) PATH="${PIPX_BIN_DIR}:${PATH}" ;;
    esac
    export PATH

    if command -v vcs &>/dev/null; then
        log_info "vcs ($(vcs --version)) is now available."
    else
        log_warn "vcs was installed but is not on PATH. Add ${PIPX_BIN_DIR} to your PATH."
    fi

    log_info "Build dependencies installed."
}

download_autoware_artifacts() {
    log_info "Downloading Autoware artifacts..."

    # Remove system ansible (Ubuntu 22.04 ships an old version)
    sudo apt-get purge -y ansible 2>/dev/null || true

    sudo apt-get update
    sudo apt-get install -y pipx

    # Ensure pipx binaries are on PATH in this shell invocation
    PIPX_BIN_DIR="${USER_HOME}/.local/bin"
    sudo -u "$TARGET_USER" python3 -m pipx ensurepath
    case ":${PATH}:" in
        *":${PIPX_BIN_DIR}:") ;;
        *) PATH="${PIPX_BIN_DIR}:${PATH}" ;;
    esac
    export PATH

    sudo -u "$TARGET_USER" pipx install --include-deps --force "ansible==6.*"

    # Clone to a temp path so we don't pollute the user's home
    local autoware_tmp
    autoware_tmp="${USER_HOME}/.cache/openadkit/autoware-clone"
    rm -rf "$autoware_tmp"
    git clone --depth 1 https://github.com/autowarefoundation/autoware.git "$autoware_tmp"

    # Download artifacts into the user's home
    local data_dir="${USER_HOME}/autoware_data"
    mkdir -p "$data_dir"

    cd "$autoware_tmp"
    ansible-galaxy collection install -f -r "ansible-galaxy-requirements.yaml"
    ansible-playbook autoware.dev_env.download_artifacts \
        -e "data_dir=${data_dir}"

    sudo chown -R "${TARGET_USER}:" "$data_dir"

    # Clean up clone
    rm -rf "$autoware_tmp"

    log_info "Autoware artifacts downloaded to ${data_dir}."
}

download_sample_data() {
    local deployment="${1:-all}"
    local force="${2:-false}"

    log_info "Downloading sample map/rosbag data for deployments..."

    # Self-contained sample data fetcher used by host setup and release bundles.
    local S3_BASE="https://autoware-files.s3.us-west-2.amazonaws.com"
    local TIER4_TAG="25.0.20"
    local TIER4_RAW="https://raw.githubusercontent.com/tier4/scenario_simulator_v2/${TIER4_TAG}/map/kashiwanoha_map/map"
    local MAP_ROOT="${AUTOWARE_MAP_DIR:-${USER_HOME}/autoware_map}"
    local TMP
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT

    if ! command -v curl >/dev/null 2>&1; then
        log_error "'curl' is required"
        return 1
    fi

    # ---- helpers ----
    sha256_verify() {
        local got
        if command -v sha256sum >/dev/null 2>&1; then
            got="$(sha256sum "$1" | awk '{print $1}')"
        elif command -v shasum >/dev/null 2>&1; then
            got="$(shasum -a 256 "$1" | awk '{print $1}')"
        else
            log_error "need 'sha256sum' or 'shasum' to verify downloads"
            return 1
        fi
        if [ "$got" != "$2" ]; then
            log_error "checksum mismatch for $1 (expected $2, got $got)"
            return 1
        fi
    }

    fetch_zip() {
        local url="$1" sum="$2" name="$3" target="${MAP_ROOT}/$3"
        if [ "$force" != true ] && [ -d "$target" ]; then
            log_info "$name already present at $target (use --force to re-download)"
            return 0
        fi
        if ! command -v unzip >/dev/null 2>&1; then
            log_error "'unzip' is required"
            return 1
        fi
        log_info "Downloading $name ..."
        curl -fL --retry 3 -o "${TMP}/${name}.zip" "$url"
        sha256_verify "${TMP}/${name}.zip" "$sum"
        mkdir -p "$MAP_ROOT"
        unzip -oq "${TMP}/${name}.zip" -d "$MAP_ROOT"
        log_info "$name -> $target"
    }

    fetch_kashiwanoha() {
        local target="${MAP_ROOT}/kashiwanoha_map"
        if [ "$force" != true ] && [ -d "$target" ]; then
            log_info "kashiwanoha_map already present at $target (use --force to re-download)"
            return 0
        fi
        log_info "Downloading kashiwanoha_map (tier4 scenario_simulator_v2 @ ${TIER4_TAG}) ..."
        local stage="${TMP}/kashiwanoha_map"
        mkdir -p "$stage"
        local curl_args=() f
        for f in lanelet2_map.osm pointcloud_map.pcd global_map_center.pcd.yaml \
                 lanelet2_map_provider.osm.yaml map.map_publisher.yaml; do
            curl_args+=(-o "${stage}/${f}" "${TIER4_RAW}/${f}")
        done
        curl -fL --retry 3 "${curl_args[@]}"
        mkdir -p "$MAP_ROOT"
        rm -rf "$target"
        mv "$stage" "$target"
        log_info "kashiwanoha_map -> $target"
    }

    fetch_planning_simulation() {
        fetch_zip \
            "${S3_BASE}/maps/demos/sample-map-planning.zip" \
            "5536fce7bb8db7688fdf94ec004118b898637ad0d5b6175108b10989dd6e93b9" \
            "sample-map-planning"
    }

    fetch_logging_simulation() {
        fetch_zip \
            "${S3_BASE}/maps/demos/sample-map-rosbag.zip" \
            "07e2da0b0bf12e2324f7083c2ce5556fb8044c50cef1da6428ab9084c3903bc8" \
            "sample-map-rosbag"
        fetch_zip \
            "${S3_BASE}/recordings/bags/demos/sample-rosbag.zip" \
            "5f9d36353393b3d249212153c19049822b1298db56512aa045b4f7f6fc37cf88" \
            "sample-rosbag"
        mkdir -p "${USER_HOME}/autoware_data"
        chown "${TARGET_USER}:" "${USER_HOME}/autoware_data" 2>/dev/null || true
        log_info "NOTE: logging-simulation also needs Autoware perception artifacts in ~/autoware_data"
        log_info "      (download them with: install.sh --download-artifacts)."
    }

    case "$deployment" in
        all|"")
            fetch_planning_simulation
            fetch_logging_simulation
            fetch_kashiwanoha
            ;;
        planning-simulation)
            fetch_planning_simulation
            ;;
        logging-simulation)
            fetch_logging_simulation
            ;;
        scenario-simulation|zenoh-bridge)
            fetch_kashiwanoha
            ;;
        carla-simulation)
            log_info "carla-simulation downloads its assets via deployments/carla-simulation/start-carla-e2e-demo.sh."
            return 0
            ;;
        *)
            log_error "Unknown deployment for sample-data: $deployment"
            return 1
            ;;
    esac

    log_info "Sample data downloaded to ${MAP_ROOT}."
}

verify_installation() {
    log_info "Running post-install verification..."

    # Verify Docker is usable in the current session
    if ! sg docker -c "docker run --rm hello-world" &>/dev/null; then
        log_error "Docker verification failed. Ensure your user is in the 'docker' group and the Docker daemon is running."
        return 1
    fi
    log_info "Docker smoke test passed."

    # Verify NVIDIA runtime if requested and GPU is available
    if [ "$INSTALL_NVIDIA" = true ] && command -v nvidia-smi &>/dev/null; then
        log_info "Pulling NVIDIA CUDA test image for GPU verification..."
        if sg docker -c "docker pull nvidia/cuda:12.2.0-base-ubuntu22.04" &>/dev/null; then
            if sg docker -c "docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi" &>/dev/null; then
                log_info "NVIDIA GPU runtime verification passed."
            else
                log_warn "NVIDIA GPU runtime verification failed. GPU containers may not work."
            fi
        else
            log_warn "Could not pull NVIDIA CUDA test image; skipping GPU runtime verification."
        fi
    elif [ "$INSTALL_NVIDIA" = true ]; then
        log_warn "nvidia-smi not found on host; skipping GPU runtime verification."
    fi

    log_info "Post-install verification completed."
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                print_help
                exit 0
                ;;
            --no-nvidia)
                INSTALL_NVIDIA=false
                shift
                ;;
            --download-artifacts)
                DOWNLOAD_ARTIFACTS=true
                shift
                ;;
            --build-deps)
                INSTALL_BUILD_DEPS=true
                shift
                ;;
            --download-samples)
                DOWNLOAD_SAMPLES=true
                shift
                ;;
            --verify)
                RUN_VERIFY=true
                shift
                ;;
            --force)
                log_error "--force is only valid with: install.sh sample-data [DEPLOYMENT] --force"
                print_help
                exit 1
                ;;
            *)
                log_error "Unknown option: $1"
                print_help
                exit 1
                ;;
        esac
    done
}

run_sample_data_command() {
    local deployment="all"
    local deployment_set="false"
    local force="false"

    shift
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                print_help
                exit 0
                ;;
            --force)
                force=true
                shift
                ;;
            -*)
                log_error "Unknown sample-data option: $1"
                print_help
                exit 1
                ;;
            *)
                if [ "$deployment_set" = true ]; then
                    log_error "Unexpected sample-data argument: $1"
                    print_help
                    exit 1
                fi
                deployment="$1"
                deployment_set=true
                shift
                ;;
        esac
    done

    download_sample_data "$deployment" "$force"
    log_info "Sample data installation completed."
}

#### Main ####
if [[ "${1:-}" == "sample-data" ]]; then
    run_sample_data_command "$@"
    exit 0
fi

parse_args "$@"
require_sudo
check_os

install_docker

if [ "$INSTALL_NVIDIA" = true ]; then
    install_nvidia_container_toolkit
fi

if [ "$INSTALL_BUILD_DEPS" = true ]; then
    install_build_dependencies
fi

if [ "$DOWNLOAD_ARTIFACTS" = true ]; then
    download_autoware_artifacts
fi

if [ "$DOWNLOAD_SAMPLES" = true ]; then
    download_sample_data all false
fi

if [ "$RUN_VERIFY" = true ]; then
    verify_installation
fi

log_info "Installation completed."

# If Docker was freshly installed, remind the user about group membership.
# For non-interactive / pipe usage we can't newgrp, so print a clear note.
if ! sg docker -c "docker version" &>/dev/null; then
    log_warn "Your user is in the 'docker' group, but the change is not active in this shell."
    log_warn "Run the following command to use Docker without sudo in the current terminal:"
    echo "  newgrp docker"
    log_warn "Or log out and log back in for the change to take effect globally."
fi
