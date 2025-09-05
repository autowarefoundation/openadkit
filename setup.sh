#!/usr/bin/env bash
# shellcheck disable=SC1091

set -e
SCRIPT_DIR=$(readlink -f "$(dirname "$0")")
CLR_GREEN="\033[32m"
CLR_RED="\033[31m"
CLR_RESET="\033[0m"
INSTALL_NVIDIA=false

#### Functions ####
print_help() {
    echo "Setup runtime environment for Autoware Open AD Kit"
    echo "Usage: setup.sh [OPTIONS]"
    echo "Options:"
    echo "  --help          Display this help message"
    echo "  -h              Display this help message"
    echo "  --nvidia        Install NVIDIA container toolkit"
    echo ""
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                print_help
                exit 0
                ;;
            --nvidia)
                INSTALL_NVIDIA=true
                shift
                ;;
            *)
                echo "Unknown option: $1"
                print_help
                exit 1
                ;;
        esac
    done
}

install_nvidia_container_toolkit() {
    echo "Installing NVIDIA Container Toolkit..."
    
    # Add NVIDIA container toolkit GPG key
    sudo curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    
    # Add NVIDIA container toolkit repository
    echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/$(dpkg --print-architecture) /" | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
    
    # Install NVIDIA Container Toolkit
    sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
    
    # Add NVIDIA runtime support to docker engine
    sudo nvidia-ctk runtime configure --runtime=docker
    
    # Restart docker daemon
    sudo systemctl restart docker
    
    echo -e "${CLR_GREEN}NVIDIA Container Toolkit installed successfully!${CLR_RESET}"
}

install_docker() {
    echo "Installing Docker..."

    if command -v docker &> /dev/null; then
        echo "Docker is already installed. Skipping installation."
        return
    fi

    # Remove old docker packages
    for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do 
        sudo apt-get remove -y "$pkg" 2>/dev/null || true
    done

    # Install ca-certificates curl
    sudo apt-get update && sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    # Add Docker's official GPG key
    echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker
    sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Add user to docker group
    sudo groupadd docker 2>/dev/null || true
    sudo usermod -aG docker "$USER"

    echo -e "${CLR_GREEN}Docker installed successfully!${CLR_RESET}"
}

#### Main ####
parse_args "$@"

if ! sudo -n true 2>/dev/null; then
    echo -e "${CLR_RED}This script requires sudo privileges. Please run with a user that has sudo access.${CLR_RESET}"
    exit 1
fi

install_docker
[ "$INSTALL_NVIDIA" = true ] && install_nvidia_container_toolkit

echo -e "${CLR_GREEN}Setup completed!${CLR_RESET}"
echo "Please log out and log back in for Docker group changes to take effect."
