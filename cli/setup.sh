#!/usr/bin/env bash
set -euo pipefail

INSTALL_GPU=false
RUN_CHECK=true
TARGET_USER=$(id -un)
FORCE_DOCKER_INSTALL=${OPENADKIT_CI_FORCE_DOCKER_INSTALL:-false}
DOCKER_GROUP_ADDED=false

log() { printf '[openadkit] %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
usage_fail() { printf 'error: %s\n' "$*" >&2; exit 2; }

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

user_in_docker_group() {
  [[ " $(id -nG "$TARGET_USER") " == *" docker "* ]]
}

docker_stack_ready() {
  [[ $FORCE_DOCKER_INSTALL != true ]] \
    && command -v docker >/dev/null 2>&1 \
    && compose_capable
}

collect_missing_packages() {
  local pkg
  MISSING_PACKAGES=()
  for pkg in "${RUNTIME_PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
      MISSING_PACKAGES+=("$pkg")
    fi
  done
}

ensure_docker_group() {
  if user_in_docker_group; then
    return 0
  fi
  sudo groupadd docker 2>/dev/null || true
  sudo usermod -aG docker "$TARGET_USER"
  DOCKER_GROUP_ADDED=true
}

docker_run() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  else
    sudo docker "$@"
  fi
}

install_docker() {
  if docker_stack_ready; then
    log "Docker and Compose are already available"
    if ! docker info >/dev/null 2>&1 && ! sudo docker info >/dev/null 2>&1; then
      log "starting the Docker daemon"
      sudo systemctl enable --now docker
    fi
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
  ensure_docker_group
}

nvidia_gl_libraries_present() {
  # No pipe: under pipefail, grep -q's early exit can fail ldconfig with
  # SIGPIPE and report a present library as missing.
  local libraries
  libraries="$(ldconfig -p 2>/dev/null || true)"
  grep -q 'libGLX_nvidia\.so' <<<"${libraries}"
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

  local driver_version driver_branch pkg compute_pkg compute_ver gl_ver dep dep_ver
  local -a install_pkgs

  driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | awk 'NR == 1')"
  driver_version="${driver_version//[[:space:]]/}"
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
  if ! command -v nvidia-ctk >/dev/null 2>&1; then
    log "installing NVIDIA Container Toolkit"
    # gnupg dearmors the repository key; refresh the lists it installs from.
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends gnupg
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
  local runtimes
  runtimes="$(sudo docker info --format '{{json .Runtimes}}' || true)"
  if ! grep -q '"nvidia"' <<<"${runtimes}"; then
    local config=/etc/docker/daemon.json backup=
    if sudo test -f "$config"; then
      backup=$(mktemp)
      sudo cp -a "$config" "$backup"
    fi
    if ! sudo nvidia-ctk runtime configure --runtime=docker \
      || ! sudo python3 -I -c 'import json,sys; json.load(open(sys.argv[1]))' "$config" \
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

DDS_SYSCTL=/etc/sysctl.d/99-openadkit-dds.conf

# Every deployment moves point clouds between containers over DDS, GPU or not.
# deployments/shared/cyclonedds.xml asks for the buffer sizes it needs; these
# only raise the caps on what a socket may ask for, so sockets that ask for
# nothing keep the kernel defaults.
dds_buffer_settings() {
  cat <<'EOF'
# Open AD Kit: let CycloneDDS request large UDP buffers for sensor data.
net.core.rmem_max=2147483647
net.core.wmem_max=2147483647
EOF
}

dds_buffers_configured() {
  [[ -f $DDS_SYSCTL ]] && cmp --silent <(dds_buffer_settings) "$DDS_SYSCTL"
}

configure_dds_buffers() {
  local temporary
  if dds_buffers_configured; then
    log "kernel UDP buffer limits for DDS are already configured"
    return 0
  fi
  temporary=$(mktemp)
  trap 'rm -f "$temporary"; trap - RETURN' RETURN
  dds_buffer_settings >"$temporary"
  log "configuring kernel UDP buffer limits for DDS"
  sudo install -m 0644 "$temporary" "$DDS_SYSCTL"
  sudo sysctl --system >/dev/null
}


main() {
if [[ ${1:-} != setup ]]; then
  usage_fail "setup helper must be invoked through openadkit setup"
fi
shift
while (($#)); do
  case "$1" in
    --gpu) INSTALL_GPU=true ;;
    --no-check) RUN_CHECK=false ;;
    -h|--help)
      cat <<'EOF'
Usage: openadkit setup [--gpu] [--no-check]

Installs the Ubuntu host dependencies needed to run Open AD Kit, raises the
kernel's UDP buffer limits for DDS, and runs a test container to confirm that
Docker works.

  --gpu        also install the NVIDIA Container Toolkit, and test the GPU
  --no-check   skip the test containers, for a host that cannot pull them
EOF
      exit 0
      ;;
    *) usage_fail "unknown setup option: $1" ;;
  esac
  shift
done

if [[ $EUID -eq 0 ]]; then
  fail "run openadkit setup as your normal user; it requests sudo when needed"
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
# The toolkit and the OpenGL libraries follow the host's driver.
if [[ $INSTALL_GPU == true ]] && ! nvidia-smi >/dev/null 2>&1; then
  fail "nvidia-smi failed; install the NVIDIA driver first (and reboot), then rerun openadkit setup --gpu"
fi

RUNTIME_PACKAGES=(ca-certificates curl git gzip python3 tar)
MISSING_PACKAGES=()

# Deployments override services they include, which Compose rejects before
# 5.0 ("conflicts with imported resource"). Probe that instead of a version.
collect_missing_packages
# Docker CE conflicts with the distribution's docker.io and containerd; never
# replace an engine the host already runs.
if [[ $FORCE_DOCKER_INSTALL != true ]] && command -v docker >/dev/null 2>&1 && ! compose_capable; then
  fail "Docker is installed but Docker Compose 5.0 or newer is missing; install Docker's docker-compose-plugin (https://docs.docker.com/compose/install/linux/) and rerun setup"
fi
need_sudo=false
if ((${#MISSING_PACKAGES[@]} > 0)) || ! docker_stack_ready || ! user_in_docker_group; then
  need_sudo=true
fi
if [[ $INSTALL_GPU == true ]] || ! dds_buffers_configured; then
  need_sudo=true
fi
# A stopped daemon, or one this user cannot reach yet, is checked with sudo.
if ! docker info >/dev/null 2>&1; then
  need_sudo=true
fi
if [[ $need_sudo == true ]]; then
  sudo -v
fi

if ((${#MISSING_PACKAGES[@]} > 0)); then
  log "installing Open AD Kit runtime dependencies"
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends "${MISSING_PACKAGES[@]}"
else
  log "runtime packages are already installed"
fi
install_docker
configure_dds_buffers

if [[ $INSTALL_GPU == true ]]; then
  install_gpu
fi

if [[ $RUN_CHECK == true ]]; then
  log "checking Docker with a test container (--no-check skips this)"
  docker_run run --rm hello-world >/dev/null
  if [[ $INSTALL_GPU == true ]]; then
    nvidia_gl_libraries_present || fail "NVIDIA OpenGL/Vulkan libraries are missing"
    docker_run run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi >/dev/null
  fi
fi

log "setup completed"
if [[ $DOCKER_GROUP_ADDED == true ]]; then
  log "Docker group membership was added for ${TARGET_USER}"
  log "run 'newgrp docker' to start a shell with the new membership, then run Open AD Kit"
elif ! docker info >/dev/null 2>&1; then
  log "log out and back in, or run 'newgrp docker', to activate Docker group membership"
fi
}

# Sourceable for tests: only a direct run sets up the host.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
