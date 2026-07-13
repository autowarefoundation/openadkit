#!/usr/bin/env bash
set -euo pipefail

USE_COLOR=true
if [[ ! -t 1 ]]; then
  USE_COLOR=false
fi

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
  sudo ./install.sh

  # Install Docker only (no NVIDIA)
  sudo ./install.sh --no-nvidia

  # Download artifacts + install Docker
  sudo ./install.sh --download-artifacts

  # Full developer environment: Docker + NVIDIA + build deps + samples + verify
  sudo ./install.sh --build-deps --download-samples --verify

  # Download all sample data without host setup
  ./install.sh sample-data

  # Re-download data for one deployment
  ./install.sh sample-data planning-simulation --force
EOF
}

log_info()  { if [ "$USE_COLOR" = true ]; then echo -e "${CLR_GREEN}[INFO]${CLR_RESET} $*"; else echo "[INFO] $*"; fi; }
log_warn()  { if [ "$USE_COLOR" = true ]; then echo -e "${CLR_YELLOW}[WARN]${CLR_RESET} $*"; else echo "[WARN] $*"; fi; }
log_error() { if [ "$USE_COLOR" = true ]; then echo -e "${CLR_RED}[ERROR]${CLR_RESET} $*"; else echo "[ERROR] $*"; fi; }

PIPX_BIN_DIR="${USER_HOME}/.local/bin"

ensure_pipx_on_path() {
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" python3 -m pipx ensurepath
    case ":${PATH}:" in
        *":${PIPX_BIN_DIR}:") ;;
        *) PATH="${PIPX_BIN_DIR}:${PATH}" ;;
    esac
    export PATH
}

require_sudo() {
    if [[ $EUID -eq 0 ]]; then
        return 0
    fi

    if [[ -t 0 ]]; then
        sudo -v
    elif ! sudo -n true 2>/dev/null; then
        log_error "This script requires sudo privileges."
        echo "Please run with a user that has sudo access, e.g.:"
        echo "  sudo ./install.sh"
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

    if [[ "${VERSION_ID:-}" != "22.04" && "${VERSION_ID:-}" != "24.04" ]]; then
        log_warn "Untested Ubuntu version: ${VERSION_ID:-unknown}. Validated on 22.04 (Jammy) and 24.04 (Noble). Continuing anyway."
    fi
}

install_nvidia_container_toolkit() {
    if command -v nvidia-ctk &>/dev/null; then
        log_info "NVIDIA Container Toolkit is already installed ($(nvidia-ctk --version)). Skipping."
        return
    fi

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

docker_compose_supports_repo_graph() {
    local probe_dir
    local result=1
    probe_dir="$(mktemp -d)"

    cat > "${probe_dir}/base.yaml" <<'EOF'
services:
  capability-probe:
    image: busybox:latest
    environment:
      OPENADKIT_BASE: "true"
EOF
    cat > "${probe_dir}/overlay.yaml" <<'EOF'
include:
  - path: base.yaml
services:
  capability-probe:
    environment:
      OPENADKIT_OVERRIDE: "true"
EOF

    if (
        cd "$probe_dir"
        docker compose -f overlay.yaml config -q
    ) &>/dev/null; then
        result=0
    fi

    rm -rf "$probe_dir"
    return "$result"
}

ensure_docker_group() {
    sudo groupadd docker 2>/dev/null || true
    sudo usermod -aG docker "$TARGET_USER"
}

install_docker() {
    local docker_cli=false
    local compose_capable=false
    local buildx_available=false
    local install_required=false
    local docker_version
    local buildx_version
    local ci_force_install=false
    local -a docker_install_args

    if command -v docker &>/dev/null && docker_version="$(docker --version 2>/dev/null)"; then
        docker_cli=true
        log_info "Docker CLI is available (${docker_version})."
    else
        log_warn "Docker CLI is not available."
    fi

    if [ "$docker_cli" = true ] && docker_compose_supports_repo_graph; then
        compose_capable=true
        log_info "Docker Compose supports include with service overrides."
    else
        log_warn "Docker Compose is missing or cannot parse include with service overrides."
    fi

    if [ "$docker_cli" = true ] && buildx_version="$(docker buildx version 2>/dev/null)"; then
        buildx_available=true
        log_info "Docker Buildx is available (${buildx_version})."
    else
        log_warn "Docker Buildx is missing."
    fi

    if [ "$docker_cli" != true ] || [ "$compose_capable" != true ] || [ "$buildx_available" != true ]; then
        install_required=true
    fi

    if [ "${OPENADKIT_CI_FORCE_DOCKER_INSTALL:-false}" = true ]; then
        if [ "${CI:-false}" != true ]; then
            log_error "OPENADKIT_CI_FORCE_DOCKER_INSTALL is restricted to disposable CI environments."
            return 1
        fi
        log_info "Forcing official Docker package installation for CI validation."
        ci_force_install=true
        install_required=true
    fi

    if [ "$install_required" = true ]; then
        log_info "Installing official Docker packages and plugins..."

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

        # Reuse an existing official repository instead of creating duplicate
        # apt source entries on pre-provisioned hosts.
        if grep -Rqs 'download\.docker\.com/linux/ubuntu' \
            /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
            log_info "Docker's official apt repository is already configured."
        else
            echo \
            "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
            $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
            | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        fi

        sudo apt-get update
        docker_install_args=(-y)
        if [ "$ci_force_install" = true ]; then
            # Disposable CI images sometimes hold their preinstalled Docker
            # packages. The force switch is already rejected outside CI.
            docker_install_args+=(--allow-change-held-packages)
        fi
        sudo apt-get install "${docker_install_args[@]}" docker-ce docker-ce-cli containerd.io \
            docker-buildx-plugin docker-compose-plugin

        # Ensure Docker starts on boot
        sudo systemctl enable --now docker

        log_info "Official Docker packages installed successfully."
    else
        log_info "Required Docker CLI, Compose, and Buildx capabilities are already available."
    fi

    # Group reconciliation is required even when all Docker capabilities were
    # already present (for example on a pre-provisioned workstation).
    ensure_docker_group

    if ! command -v docker &>/dev/null || ! docker --version &>/dev/null; then
        log_error "Docker CLI is unavailable after installation."
        return 1
    fi
    if ! docker_compose_supports_repo_graph; then
        log_error "Docker Compose cannot parse include with service overrides after installation."
        return 1
    fi
    if ! docker buildx version &>/dev/null; then
        log_error "Docker Buildx is unavailable after installation."
        return 1
    fi
}

install_build_dependencies() {
    log_info "Installing build dependencies (jq, pipx, vcs2l, python3-yaml, unzip, git)..."

    sudo apt-get update
    sudo apt-get install -y jq python3-yaml unzip git pipx

    # Install vcs2l via pipx as the target user (not root), because pipx
    # drops packages into the user's home directory.
    sudo -u "$TARGET_USER" pipx install --force vcs2l

    # Ensure pipx binaries are on PATH in this shell invocation
    ensure_pipx_on_path

    if command -v vcs &>/dev/null; then
        log_info "vcs ($(vcs --version)) is now available."
    else
        log_warn "vcs was installed but is not on PATH. Add ${PIPX_BIN_DIR} to your PATH."
    fi

    log_info "Build dependencies installed."
}

download_autoware_artifacts() {
    log_info "Downloading Autoware artifacts..."

    sudo apt-get update
    sudo apt-get install -y git pipx

    # Ensure pipx binaries are on PATH in this shell invocation
    ensure_pipx_on_path

    # Match Autoware's installer. Ansible 6 bundles ansible-core 2.13, which
    # fails on Ubuntu 24.04's Python 3.12 during HTTPS artifact downloads.
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" \
        pipx install --include-deps --force "ansible==10.*"

    # Clone to a temp path so we don't pollute the user's home
    local autoware_tmp
    local command_status=0
    local target_path="${PIPX_BIN_DIR}:${PATH}"
    autoware_tmp="${USER_HOME}/.cache/openadkit/autoware-clone"
    sudo install -d -m 0755 -o "$TARGET_USER" -g "$(id -gn "$TARGET_USER")" \
        "$(dirname "$autoware_tmp")"
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" rm -rf "$autoware_tmp"
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" \
        git clone --depth 1 https://github.com/autowarefoundation/autoware.git "$autoware_tmp"

    # Download artifacts into the user's home
    local data_dir="${USER_HOME}/autoware_data"
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" mkdir -p "$data_dir"

    if ! (
        cd "$autoware_tmp"
        sudo -u "$TARGET_USER" env HOME="$USER_HOME" PATH="$target_path" \
            ansible-galaxy collection install -f -r "ansible-galaxy-requirements.yaml"
        sudo -u "$TARGET_USER" env HOME="$USER_HOME" PATH="$target_path" \
            ansible-playbook autoware.dev_env.download_artifacts \
            -e "data_dir=${data_dir}"
    ); then
        command_status=1
    fi

    # Clean up clone
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" rm -rf "$autoware_tmp"

    if [ "$command_status" -ne 0 ]; then
        log_error "Autoware artifact download failed."
        return "$command_status"
    fi

    log_info "Autoware artifacts downloaded to ${data_dir}."
}

download_sample_data() {
    local deployment="${1:-all}"
    local force="${2:-false}"

    log_info "Downloading sample map/rosbag data for deployments..."

    # Self-contained sample data fetcher used by host setup and release bundles.
    local S3_BASE="https://autoware-files.s3.us-west-2.amazonaws.com"
    # Pin to the commit SHA that the 25.0.20 tag resolves to, not the mutable
    # tag itself, so downloads are reproducible and checksums are stable.
    local TIER4_SHA="63ccb1da6944a7be4427440bf200ad62281dc899"
    local TIER4_RAW="https://raw.githubusercontent.com/tier4/scenario_simulator_v2/${TIER4_SHA}/map/kashiwanoha_map/map"
    local MAP_ROOT="${AUTOWARE_MAP_DIR:-${USER_HOME}/autoware_map}"
    local TMP
    TMP="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${TMP}'" EXIT

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
        log_info "Downloading kashiwanoha_map (tier4 scenario_simulator_v2 @ ${TIER4_SHA}) ..."
        local stage="${TMP}/kashiwanoha_map"
        mkdir -p "$stage"
        local files=(
            "lanelet2_map.osm:91a9126e561783c1dc833e4de84f4d667888cc0466eb5983660cff6c70dd316f"
            "pointcloud_map.pcd:6ac84b21103b32ae43ac387d4905285442d250657f5ea100b12dfb59a1c758da"
            "global_map_center.pcd.yaml:78168b167bf6f0d7e432392712798b8c0cee90fff75c5d1414c59b6f892e87d6"
            "lanelet2_map_provider.osm.yaml:f03a11f7f10012b5d56851786a8fdd5511e8ac94b2892b0ed1e01a485a5edfff"
            "map.map_publisher.yaml:68df5e92c9bb174178b018f5e10561b6c9019e14decdd2a02a9aebd784b181ab"
        )
        local entry name sum
        for entry in "${files[@]}"; do
            name="${entry%%:*}"
            sum="${entry##*:}"
            curl -fL --retry 3 -o "${stage}/${name}" "${TIER4_RAW}/${name}"
            sha256_verify "${stage}/${name}" "$sum"
        done
        mkdir -p "$MAP_ROOT"
        rm -rf "$target"
        if ! mv "$stage" "$target"; then
            log_error "Failed to move $stage to $target"
            return 1
        fi
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

    if [[ $EUID -eq 0 && "$TARGET_USER" != "root" ]]; then
        chown -R "${TARGET_USER}:" "$MAP_ROOT"
    fi
    log_info "Sample data downloaded to ${MAP_ROOT}."
}

verify_installation() {
    log_info "Running post-install verification..."

    if ! docker_compose_supports_repo_graph; then
        log_error "Docker Compose capability verification failed."
        return 1
    fi
    log_info "Docker Compose capability test passed."

    if ! docker buildx version &>/dev/null; then
        log_error "Docker Buildx verification failed."
        return 1
    fi
    log_info "Docker Buildx capability test passed."

    # Verify Docker is usable. The script has sudo access (via require_sudo), so
    # use sudo for docker commands — the target user may not be in the docker
    # group until the next login.
    if ! sudo docker run --rm hello-world &>/dev/null; then
        log_error "Docker verification failed. Ensure the Docker daemon is running."
        return 1
    fi
    log_info "Docker smoke test passed."

    # Verify NVIDIA runtime if requested and GPU is available
    if [ "$INSTALL_NVIDIA" = true ] && command -v nvidia-smi &>/dev/null; then
        log_info "Pulling NVIDIA CUDA test image for GPU verification..."
        if sudo docker pull nvidia/cuda:12.2.0-base-ubuntu22.04 &>/dev/null; then
            if sudo docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
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

    if ! download_sample_data "$deployment" "$force"; then
        exit 1
    fi
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
    if ! download_sample_data all false; then
        exit 1
    fi
fi

if [ "$RUN_VERIFY" = true ]; then
    verify_installation
fi

log_info "Installation completed."

# If Docker was freshly installed, remind the user about group membership.
# The non-interactive / pipe usage can't newgrp, so print a clear note.
if ! sudo -u "$TARGET_USER" docker version &>/dev/null; then
    log_warn "Your user is in the 'docker' group, but the change is not active in this shell."
    log_warn "Run the following command to use Docker without sudo in the current terminal:"
    echo "  newgrp docker"
    log_warn "Or log out and log back in for the change to take effect globally."
fi

# Remind about pipx binaries (vcs, etc.) if not on PATH.
if ! command -v vcs &>/dev/null && [ -x "${PIPX_BIN_DIR}/vcs" ]; then
    log_info "Run 'export PATH=\"\$HOME/.local/bin:\$PATH\"' to use vcs in this shell,"
    log_info "or log out and back in for the change to take effect globally."
fi
