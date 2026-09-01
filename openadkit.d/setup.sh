#!/usr/bin/env bash
set -euo pipefail

INSTALL_GPU=false
RUN_VERIFY=false
TARGET_USER=${SUDO_USER:-$(id -un)}
FORCE_DOCKER_INSTALL=${OPENADKIT_CI_FORCE_DOCKER_INSTALL:-false}

log() { printf '[openadkit] %s\n' "$*"; }
fail() { printf '[openadkit] error: %s\n' "$*" >&2; exit 1; }

if [[ ${1:-} != setup ]]; then
  fail "setup helper must be invoked through ./openadkit setup"
fi
shift
while (($#)); do
  case "$1" in
    --gpu) INSTALL_GPU=true ;;
    --verify) RUN_VERIFY=true ;;
    -h|--help)
      cat <<'EOF'
Usage: ./openadkit setup [--gpu] [--verify]

Installs the Ubuntu host dependencies needed to run Open AD Kit.
EOF
      exit 0
      ;;
    *) fail "unknown setup option: $1" ;;
  esac
  shift
done

if [[ $EUID -eq 0 ]]; then
  fail "run ./openadkit setup as your normal user; it requests sudo when needed"
fi
if [[ $FORCE_DOCKER_INSTALL == true && ${CI:-false} != true ]]; then
  fail "OPENADKIT_CI_FORCE_DOCKER_INSTALL is restricted to disposable CI hosts"
fi
[[ -r /etc/os-release ]] || fail "only Ubuntu hosts are supported"
# shellcheck disable=SC1091
source /etc/os-release
[[ ${ID:-} == ubuntu ]] || fail "unsupported OS: ${ID:-unknown}; expected Ubuntu"
case "$(uname -m)" in
  x86_64|amd64|aarch64|arm64) ;;
  *) fail "unsupported architecture: $(uname -m)" ;;
esac

sudo -v

compose_capable() {
  local temporary
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"; trap - RETURN' RETURN
  cat >"$temporary/base.yaml" <<'EOF'
services:
  probe:
    image: busybox:1.36.1
EOF
  cat >"$temporary/overlay.yaml" <<'EOF'
include:
  - path: base.yaml
services:
  probe:
    environment:
      OPENADKIT_PROBE: "true"
EOF
  (
    cd "$temporary"
    env -u COMPOSE_ENV_FILES -u COMPOSE_FILE -u COMPOSE_PROFILES -u COMPOSE_PROJECT_NAME \
      docker compose --project-name openadkit-capability-probe --file overlay.yaml config --quiet
  ) >/dev/null 2>&1
}

install_docker() {
  if [[ $FORCE_DOCKER_INSTALL != true ]] \
    && command -v docker >/dev/null 2>&1 \
    && docker buildx version >/dev/null 2>&1 \
    && compose_capable; then
    log "Docker, Buildx, and Compose are already available"
  else
    log "installing Docker from the official Ubuntu repository"
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
      "${UBUNTU_CODENAME:-$VERSION_CODENAME}" "$(dpkg --print-architecture)" \
      | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable --now docker
  fi
  sudo groupadd docker 2>/dev/null || true
  sudo usermod -aG docker "$TARGET_USER"
}

nvidia_gl_libraries_present() {
  ldconfig -p 2>/dev/null | grep -q 'libGLX_nvidia\.so'
}

apt_package_has_candidate() {
  local candidate
  candidate="$(apt-cache policy "$1" 2>/dev/null | awk '$1 == "Candidate:" { print $2; exit }' || true)"
  [[ -n $candidate && $candidate != "(none)" ]]
}

apt_madison_version() {
  local pkg="$1"
  local match="${2:-}"
  apt-cache madison "$pkg" 2>/dev/null | awk -F'|' -v prefix="$match" '
    {
      version=$2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", version)
      if (version == "") next
      if (prefix == "" || index(version, prefix) == 1) {
        print version
        exit
      }
    }' || true
}

install_nvidia_gl_libraries() {
  if nvidia_gl_libraries_present; then
    log "NVIDIA OpenGL/Vulkan libraries are already installed"
    return 0
  fi
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    log "nvidia-smi not found; skipping NVIDIA OpenGL/Vulkan libraries"
    return 0
  fi

  local driver_version driver_branch pkg compute_pkg compute_ver gl_ver dep dep_ver
  local -a install_pkgs

  driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | tr -d '[:space:]')"
  driver_branch="${driver_version%%.*}"
  pkg="libnvidia-gl-${driver_branch}"
  compute_pkg="libnvidia-compute-${driver_branch}"
  compute_ver="$(dpkg-query -W -f='${Version}' "$compute_pkg" 2>/dev/null || true)"

  log "installing NVIDIA OpenGL/Vulkan libraries (${pkg}) for driver ${driver_version}"
  sudo apt-get update
  if apt_package_has_candidate "$pkg"; then
    sudo apt-get install -y --no-install-recommends "$pkg"
  else
    gl_ver="$compute_ver"
    if [[ -z $gl_ver || -z $(apt_madison_version "$pkg" "$gl_ver") ]]; then
      gl_ver="$(apt_madison_version "$pkg" "$driver_version")"
    fi
    [[ -n $gl_ver ]] || gl_ver="$(apt_madison_version "$pkg")"
    [[ -n $gl_ver ]] || fail "could not find ${pkg} for NVIDIA driver ${driver_version}"
    install_pkgs=("${pkg}=${gl_ver}")
    for dep in libnvidia-egl-gbm1 libnvidia-egl-wayland1 libnvidia-egl-xcb1 libnvidia-egl-xlib1; do
      dep_ver="$(apt_madison_version "$dep")"
      [[ -n $dep_ver ]] && install_pkgs+=("${dep}=${dep_ver}")
    done
    sudo apt-get install -y --no-install-recommends "${install_pkgs[@]}"
  fi
  sudo ldconfig
  nvidia_gl_libraries_present || fail "installed ${pkg} but libGLX_nvidia is still missing"
}

install_gpu() {
  sudo apt-get install -y --no-install-recommends gnupg
  if ! command -v nvidia-ctk >/dev/null 2>&1; then
    log "installing NVIDIA Container Toolkit"
    local key list
    key=$(mktemp)
    list=$(mktemp)
    trap 'rm -f "$key" "$list"; trap - RETURN' RETURN
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | gpg --batch --yes --dearmor -o "$key"
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      >"$list"
    [[ -s $key && -s $list ]] || fail "could not download NVIDIA repository metadata"
    sudo install -m 0644 "$key" /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    sudo install -m 0644 "$list" /etc/apt/sources.list.d/nvidia-container-toolkit.list
    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit
  fi
  if ! sudo docker info --format '{{json .Runtimes}}' | grep -q '"nvidia"'; then
    local config=/etc/docker/daemon.json backup=
    if sudo test -f "$config"; then
      backup=$(mktemp)
      sudo cp -a "$config" "$backup"
    fi
    if ! sudo nvidia-ctk runtime configure --runtime=docker \
      || ! sudo python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$config" \
      || ! sudo systemctl restart docker; then
      if [[ -n $backup ]]; then
        sudo cp -a "$backup" "$config"
      else
        sudo rm -f "$config"
      fi
      sudo systemctl restart docker || true
      sudo rm -f "$backup"
      fail "NVIDIA runtime configuration failed and was rolled back"
    fi
    sudo rm -f "$backup"
  fi
  install_nvidia_gl_libraries
}

configure_dds_buffers() {
  local config temporary
  config=/etc/sysctl.d/99-openadkit-dds.conf
  temporary=$(mktemp)
  trap 'rm -f "$temporary"; trap - RETURN' RETURN
  cat >"$temporary" <<'EOF'
# Open AD Kit CycloneDDS buffers for high-bandwidth sensor data.
net.core.rmem_max=2147483647
net.core.wmem_max=2147483647
net.core.rmem_default=134217728
net.core.wmem_default=134217728
EOF
  if ! sudo test -f "$config" || ! sudo cmp --silent "$temporary" "$config"; then
    log "configuring kernel UDP buffers for DDS"
    sudo install -m 0644 "$temporary" "$config"
    sudo sysctl --system >/dev/null
  fi
}

log "installing Open AD Kit runtime dependencies"
sudo apt-get update
sudo apt-get install -y --no-install-recommends ca-certificates curl git gzip python3 python3-venv tar unzip
install_docker

if [[ $INSTALL_GPU == true ]]; then
  install_gpu
  configure_dds_buffers
fi

if [[ $RUN_VERIFY == true ]]; then
  sudo docker run --rm hello-world >/dev/null
  if [[ $INSTALL_GPU == true ]]; then
    command -v nvidia-smi >/dev/null 2>&1 || fail "nvidia-smi is unavailable"
    nvidia_gl_libraries_present || fail "NVIDIA OpenGL/Vulkan libraries are missing"
    sudo docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi >/dev/null
  fi
fi

log "setup completed"
if ! docker info >/dev/null 2>&1; then
  log "log out and back in, or run 'newgrp docker', to activate Docker group membership"
fi
