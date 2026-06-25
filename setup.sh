#!/usr/bin/env bash
set -euo pipefail

CLR_GREEN="\033[32m"
CLR_RED="\033[31m"
CLR_YELLOW="\033[33m"
CLR_RESET="\033[0m"

INSTALL_NVIDIA=true
DOWNLOAD_ARTIFACTS=false

# Resolve the real invoking user whether the script is run via sudo or directly.
TARGET_USER="${SUDO_USER:-$(id -un)}"
USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

#### Functions ####
print_help() {
    cat <<EOF
Setup runtime environment for Autoware Open AD Kit

Usage: setup.sh [OPTIONS]

Options:
  --help                  Display this help message
  -h                      Display this help message
  --no-nvidia             Skip installation of NVIDIA container toolkit
  --download-artifacts    Download Autoware artifacts (does not skip Docker)

Examples:
  # Install Docker + NVIDIA toolkit (default)
  curl -fsSL .../setup.sh | sudo bash

  # Install Docker only (no NVIDIA)
  curl -fsSL .../setup.sh | sudo bash -s -- --no-nvidia

  # Download artifacts + install Docker
  curl -fsSL .../setup.sh | sudo bash -s -- --download-artifacts
EOF
}

log_info()  { echo -e "${CLR_GREEN}[INFO]${CLR_RESET} $*"; }
log_warn()  { echo -e "${CLR_YELLOW}[WARN]${CLR_RESET} $*"; }
log_error() { echo -e "${CLR_RED}[ERROR]${CLR_RESET} $*"; }

require_sudo() {
    if ! sudo -n true 2>/dev/null; then
        log_error "This script requires sudo privileges."
        echo "Please run with a user that has sudo access, e.g.:"
        echo "  curl -fsSL .../setup.sh | sudo bash"
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
        log_warn "Untested Ubuntu version: ${VERSION_ID:-unknown}. Validated on 22.04 (Jammy)."
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
    log_warn "Please log out and log back in for Docker group changes to take effect."
}

download_autoware_artifacts() {
    log_info "Downloading Autoware artifacts..."

    # Remove system ansible (Ubuntu 22.04 ships an old version)
    sudo apt-get purge -y ansible 2>/dev/null || true

    sudo apt-get update
    sudo apt-get install -y pipx

    # Ensure pipx binaries are on PATH in this shell invocation
    PIPX_BIN_DIR="${USER_HOME}/.local/bin"
    python3 -m pipx ensurepath
    case ":${PATH}:" in
        *":${PIPX_BIN_DIR}:"*) ;;
        *) PATH="${PIPX_BIN_DIR}:${PATH}" ;;
    esac
    export PATH

    pipx install --include-deps --force "ansible==6.*"

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

    sudo chown -R "${TARGET_USER}:${TARGET_USER}" "$data_dir"

    # Clean up clone
    rm -rf "$autoware_tmp"

    log_info "Autoware artifacts downloaded to ${data_dir}."
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
            *)
                log_error "Unknown option: $1"
                print_help
                exit 1
                ;;
        esac
    done
}

#### Main ####
parse_args "$@"
require_sudo
check_os

install_docker

if [ "$INSTALL_NVIDIA" = true ]; then
    install_nvidia_container_toolkit
fi

if [ "$DOWNLOAD_ARTIFACTS" = true ]; then
    download_autoware_artifacts
fi

log_info "Setup completed."
