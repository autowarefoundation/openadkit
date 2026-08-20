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
RUN_VERIFY=false
SAMPLE_TMP=""
declare -a SAMPLE_STAGE_PATHS=()
readonly SAMPLE_DATA_CONFIGS=(
    "planning-simulation|Download the planning simulation map|true|fetch_planning_simulation"
    "logging-simulation|Download the logging simulation map and rosbag|true|fetch_logging_simulation"
    "scenario-simulation|Download the Kashiwanoha scenario map|false|fetch_kashiwanoha"
    "all|Download all non-CARLA sample data (default)|true|fetch_planning_simulation fetch_logging_simulation fetch_kashiwanoha"
)

# Resolve the real invoking user whether the script is run via sudo or directly.
TARGET_USER="${SUDO_USER:-$(id -un)}"
USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

#### Functions ####
sample_data_config() {
    local deployment="$1"
    local config name

    for config in "${SAMPLE_DATA_CONFIGS[@]}"; do
        IFS='|' read -r name _ <<< "$config"
        if [ "$name" = "$deployment" ]; then
            printf '%s\n' "$config"
            return 0
        fi
    done

    return 1
}

print_help() {
    local config name description

    cat <<EOF
Install Open AD Kit host dependencies and sample data.

Usage:
  install.sh [OPTIONS]
  install.sh sample-data [DEPLOYMENT] [OPTIONS]

Default behavior installs host dependencies (Docker, NVIDIA Container Toolkit,
and NVIDIA OpenGL/Vulkan libraries).

Commands:
  sample-data            Download sample maps/rosbags only; defaults to all sample data

Deployments for sample-data:
EOF
    for config in "${SAMPLE_DATA_CONFIGS[@]}"; do
        IFS='|' read -r name description _ <<< "$config"
        printf '  %-23s%s\n' "$name" "$description"
    done
    printf '\n'
    cat <<EOF
Options:
  --help                  Display this help message
  -h                      Display this help message
  --no-nvidia             Skip NVIDIA container toolkit and OpenGL/Vulkan libraries
  --download-artifacts    Also download Autoware artifacts after host setup
                           (unlike old setup.sh, this does NOT skip Docker/NVIDIA)
  --build-deps            Install tools needed to build images from source
                           (jq, vcs2l, python3-yaml, unzip, pipx, git)
  --verify                Run post-install smoke tests (Docker + GPU if available)
  --force                 Re-download sample data in sample-data mode

Examples:
  # Install Docker + NVIDIA toolkit (default)
  sudo ./install.sh

  # Install Docker only (no NVIDIA)
  sudo ./install.sh --no-nvidia

  # Host setup (Docker + NVIDIA) and download Autoware artifacts.
  # Still runs install_docker (idempotent if Docker is already present).
  sudo ./install.sh --download-artifacts

  # Full developer environment: host setup, then sample data
  sudo ./install.sh --build-deps --verify
  ./install.sh sample-data

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

detect_host_architecture() {
    case "$(uname -m)" in
        x86_64|amd64|aarch64|arm64) ;;
        *)
            log_error "Unsupported architecture: $(uname -m). Open AD Kit supports amd64 and arm64 hosts."
            return 1
            ;;
    esac
}

install_nvidia_container_toolkit() {
    # Clean up every temp file this function may create on return via a single
    # RETURN trap declared once, so a later trap cannot clobber an earlier one.
    local tmp_key="" tmp_list="" docker_backup=""
    # docker_backup is written via sudo cp and may be root-owned; clean with sudo.
    trap 'rm -f "$tmp_key" "$tmp_list"; [ -n "$docker_backup" ] && sudo rm -f "$docker_backup" || true' RETURN

    if command -v nvidia-ctk &>/dev/null; then
        log_info "NVIDIA Container Toolkit is already installed ($(nvidia-ctk --version))."
    else
        log_info "Installing NVIDIA Container Toolkit..."

        sudo apt-get update
        sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg2

        # Download and validate the replacement keyring and repo list into
        # temporary files first. The existing NVIDIA source is only removed once
        # both downloads succeed, so a transient network, TLS, or GPG failure
        # under `set -e` cannot disable a previously working package repository.
        tmp_key="$(mktemp)"
        tmp_list="$(mktemp)"

        # Dearmor the NVIDIA GPG key per official NVIDIA docs.
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            | gpg --batch --yes --dearmor -o "$tmp_key"
        curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
            > "$tmp_list"
        if [ ! -s "$tmp_key" ] || [ ! -s "$tmp_list" ]; then
            log_error "Failed to download a valid NVIDIA keyring or repository list; leaving existing configuration untouched."
            return 1
        fi

        # Both replacements are ready; drop stale duplicates and install atomically.
        sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit*.list
        sudo install -m 0644 "$tmp_key" /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        sudo install -m 0644 "$tmp_list" /etc/apt/sources.list.d/nvidia-container-toolkit.list

        sudo apt-get update
        sudo apt-get install -y nvidia-container-toolkit
    fi

    if sudo docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'; then
        log_info "NVIDIA runtime is already configured for Docker."
        return
    fi

    log_info "Configuring NVIDIA runtime for Docker..."

    # Docker's daemon config is host-wide: a bad rewrite or a failed restart can
    # take down every container on the machine. Back it up, validate the rewrite
    # before restarting, and roll back both the config and the daemon on any
    # failure instead of exiting under `set -e` with Docker left stopped.
    local docker_config=/etc/docker/daemon.json
    if [ -f "$docker_config" ]; then
        docker_backup="$(mktemp)"
        sudo cp -a "$docker_config" "$docker_backup"
    fi

    restore_docker() {
        log_warn "Rolling back Docker configuration and restarting the daemon..."
        if [ -n "$docker_backup" ]; then
            sudo cp -a "$docker_backup" "$docker_config"
        else
            sudo rm -f "$docker_config"
        fi
        sudo systemctl restart docker \
            || log_error "Docker failed to restart after rollback; run 'sudo systemctl status docker'."
    }

    if ! sudo nvidia-ctk runtime configure --runtime=docker; then
        log_error "nvidia-ctk could not update the Docker runtime configuration."
        restore_docker
        return 1
    fi

    # daemon.json is often root-only (0600); validate via sudo so a permission
    # error is not misreported as invalid JSON.
    if ! sudo python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$docker_config" 2>/dev/null; then
        log_error "Generated Docker configuration is not valid JSON; not restarting the daemon."
        restore_docker
        return 1
    fi

    log_warn "Restarting the Docker daemon to apply the NVIDIA runtime; this briefly interrupts running containers."
    if ! sudo systemctl restart docker; then
        log_error "Docker failed to restart with the new NVIDIA configuration."
        restore_docker
        return 1
    fi

    if ! sudo docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'; then
        log_error "NVIDIA runtime configuration did not become available in Docker."
        restore_docker
        return 1
    fi

    log_info "NVIDIA Container Toolkit configured successfully."
}

nvidia_gl_libraries_present() {
    ldconfig -p 2>/dev/null | grep -q 'libGLX_nvidia\.so'
}

apt_package_has_candidate() {
    local candidate
    candidate="$(apt-cache policy "$1" 2>/dev/null | awk '$1 == "Candidate:" { print $2; exit }' || true)"
    [ -n "$candidate" ] && [ "$candidate" != "(none)" ]
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
        log_info "NVIDIA OpenGL/Vulkan libraries are already installed."
        return 0
    fi

    if ! command -v nvidia-smi &>/dev/null; then
        log_warn "nvidia-smi not found; skipping NVIDIA OpenGL/Vulkan libraries."
        return 0
    fi

    local driver_version driver_branch pkg compute_pkg compute_ver gl_ver dep dep_ver
    local -a install_pkgs

    driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | tr -d '[:space:]')"
    driver_branch="${driver_version%%.*}"
    pkg="libnvidia-gl-${driver_branch}"
    compute_pkg="libnvidia-compute-${driver_branch}"
    compute_ver="$(dpkg-query -W -f='${Version}' "$compute_pkg" 2>/dev/null || true)"

    log_info "Installing NVIDIA OpenGL/Vulkan libraries (${pkg}) for driver ${driver_version}..."
    sudo apt-get update

    if apt_package_has_candidate "$pkg"; then
        sudo apt-get install -y --no-install-recommends "$pkg"
    else
        gl_ver="$compute_ver"
        if [ -z "$gl_ver" ] || [ -z "$(apt_madison_version "$pkg" "$gl_ver")" ]; then
            gl_ver="$(apt_madison_version "$pkg" "$driver_version")"
        fi
        if [ -z "$gl_ver" ]; then
            gl_ver="$(apt_madison_version "$pkg")"
        fi
        if [ -z "$gl_ver" ]; then
            log_error "Could not find ${pkg} for NVIDIA driver ${driver_version}."
            return 1
        fi

        install_pkgs=("${pkg}=${gl_ver}")
        for dep in libnvidia-egl-gbm1 libnvidia-egl-wayland1 libnvidia-egl-xcb1 libnvidia-egl-xlib1; do
            dep_ver="$(apt_madison_version "$dep")"
            if [ -n "$dep_ver" ]; then
                install_pkgs+=("${dep}=${dep_ver}")
            fi
        done
        sudo apt-get install -y --no-install-recommends "${install_pkgs[@]}"
    fi

    sudo ldconfig
    if ! nvidia_gl_libraries_present; then
        log_error "Installed ${pkg} but libGLX_nvidia is still missing."
        return 1
    fi
    log_info "NVIDIA OpenGL/Vulkan libraries installed."
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
    local docker_policy
    local docker_candidate
    local docker_versions
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

        sudo apt-get update
        sudo apt-get install -y ca-certificates curl

        # Add Docker's official GPG key
        sudo install -m 0755 -d /etc/apt/keyrings
        sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc

        # Write one canonical active source instead of trusting any textual URL
        # match, which could be commented out, stale, or missing signed-by.
        echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
        $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        printf '%s\n' \
            'Package: docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin' \
            'Pin: origin "download.docker.com"' \
            'Pin-Priority: 1001' \
            | sudo tee /etc/apt/preferences.d/openadkit-docker > /dev/null

        sudo apt-get update
        docker_policy=$(sudo env LC_ALL=C apt-cache policy docker-ce)
        docker_candidate=$(awk '$1 == "Candidate:" { print $2; exit }' <<< "$docker_policy")
        docker_versions=$(sudo env LC_ALL=C apt-cache madison docker-ce)
        if [ -z "$docker_candidate" ] || [ "$docker_candidate" = "(none)" ] \
            || ! awk -F '|' -v candidate="$docker_candidate" '
                {
                    version=$2
                    gsub(/^[[:space:]]+|[[:space:]]+$/, "", version)
                    if (version == candidate && $3 ~ /^[[:space:]]*https:\/\/download\.docker\.com\/linux\/ubuntu([[:space:]]|$)/) found=1
                }
                END { exit(found ? 0 : 1) }
            ' <<< "$docker_versions"; then
            log_error "Docker CE has no candidate from the configured official repository; existing Docker packages were left unchanged."
            return 1
        fi
        docker_install_args=(-y)
        if [ "$ci_force_install" = true ]; then
            # Disposable CI images sometimes hold their preinstalled Docker
            # packages. The force switch is already rejected outside CI.
            docker_install_args+=(--allow-change-held-packages)
        fi
        # APT replaces conflicting distro packages in the same transaction, so
        # a repository or download failure cannot strand the host after a
        # separate pre-emptive removal step.
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
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" pipx install --force vcs2l

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
    local AUTOWARE_REF="1.9.0"
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" rm -rf "$autoware_tmp"
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" \
        git clone --depth 1 --branch "$AUTOWARE_REF" \
        https://github.com/autowarefoundation/autoware.git "$autoware_tmp"

    # Download artifacts into the user's home
    local data_dir="${USER_HOME}/autoware_data"
    sudo -u "$TARGET_USER" env HOME="$USER_HOME" mkdir -p "$data_dir"

    if ! (
        cd "$autoware_tmp" &&
        sudo -u "$TARGET_USER" env HOME="$USER_HOME" PATH="$target_path" \
            ansible-galaxy collection install -f -r "ansible-galaxy-requirements.yaml" &&
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

preflight_sample_data_dependencies() {
    local deployment="$1"
    local config name description fetchers
    local needs_unzip=false
    local missing=()

    if ! config="$(sample_data_config "$deployment")"; then
        if [ "$deployment" = "carla-simulation" ]; then
            log_error "sample-data does not support carla-simulation."
            log_info "Use deployments/samples/carla-simulation/start-carla-e2e-demo.sh instead."
        else
            log_error "Unknown deployment for sample-data: $deployment"
        fi
        return 1
    fi
    IFS='|' read -r name description needs_unzip fetchers <<< "$config"

    command -v curl >/dev/null 2>&1 || missing+=(curl)
    command -v realpath >/dev/null 2>&1 || missing+=(realpath)
    if ! command -v sha256sum >/dev/null 2>&1 \
        && ! command -v shasum >/dev/null 2>&1; then
        missing+=("sha256sum or shasum")
    fi
    if [ "$needs_unzip" = true ] && ! command -v unzip >/dev/null 2>&1; then
        missing+=(unzip)
    fi
    # python3 is required for atomic publish (renameat2) on every sample-data path,
    # not only ZIP validation.
    if ! command -v python3 >/dev/null 2>&1; then
        missing+=(python3)
    fi
    if [ "${#missing[@]}" -gt 0 ]; then
        log_error "Missing sample download dependencies: ${missing[*]}"
        return 1
    fi
}

download_sample_data() {
    local deployment="${1:-all}"
    local force="${2:-false}"
    local config name description needs_unzip fetcher_names fetcher
    local -a fetchers

    preflight_sample_data_dependencies "$deployment"
    config="$(sample_data_config "$deployment")"
    IFS='|' read -r name description needs_unzip fetcher_names <<< "$config"
    read -r -a fetchers <<< "$fetcher_names"

    log_info "Downloading sample map/rosbag data for deployments..."

    # Self-contained sample data fetcher used by the CLI and release bundles.
    local S3_BASE="https://autoware-files.s3.us-west-2.amazonaws.com"
    # Pin to the commit SHA that the 25.0.20 tag resolves to, not the mutable
    # tag itself, so downloads are reproducible and checksums are stable.
    local TIER4_SHA="63ccb1da6944a7be4427440bf200ad62281dc899"
    local TIER4_RAW="https://raw.githubusercontent.com/tier4/scenario_simulator_v2/${TIER4_SHA}/map/kashiwanoha_map/map"
    local MAP_ROOT="${AUTOWARE_MAP_DIR:-${USER_HOME}/autoware_map}"
    local stage_path
    SAMPLE_TMP="$(mktemp -d)"
    SAMPLE_STAGE_PATHS=()

    remove_sample_temporary_paths() {
        [ -n "$SAMPLE_TMP" ] && rm -rf -- "$SAMPLE_TMP"
        for stage_path in "${SAMPLE_STAGE_PATHS[@]}"; do
            [ -n "$stage_path" ] && rm -rf -- "$stage_path"
        done
    }

    cleanup_sample_temporary_paths() {
        local status=$?
        trap - EXIT HUP INT TERM
        remove_sample_temporary_paths
        exit "$status"
    }
    trap cleanup_sample_temporary_paths EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    # ---- helpers ----
    reject_symlink_path_components() {
        local path="$1" current="/" component
        local -a components
        IFS='/' read -r -a components <<< "${path#/}"
        for component in "${components[@]}"; do
            [ -n "$component" ] || continue
            current="${current%/}/${component}"
            if [ -L "$current" ]; then
                log_error "Refusing symlink path component: $current"
                return 1
            fi
            if [ -e "$current" ] && [ ! -d "$current" ]; then
                log_error "Sample map path component is not a directory: $current"
                return 1
            fi
        done
    }

    prepare_sample_map_root() {
        MAP_ROOT="$(realpath -ms -- "$MAP_ROOT")"
        reject_symlink_path_components "$MAP_ROOT" || return 1
        if [ ! -d "$MAP_ROOT" ]; then
            mkdir -p -- "$MAP_ROOT"
        fi
        reject_symlink_path_components "$MAP_ROOT" || return 1
    }

    validate_sample_target_path() {
        local target="$1"
        if [ -L "$target" ]; then
            log_error "Refusing sample target symlink: $target"
            return 1
        fi
        if [ -e "$target" ] && [ ! -d "$target" ]; then
            log_error "Sample target is not a directory: $target"
            return 1
        fi
    }

    require_sample_file() {
        local path="$1"
        if [ -L "$path" ] || [ ! -f "$path" ] || [ ! -s "$path" ]; then
            log_error "Sample dataset is missing required file: $path"
            return 1
        fi
    }

    normalize_sample_permissions() {
        local root="$1"
        find "$root" -type d -exec chmod u+rwx,go+rx {} +
        find "$root" -type f -exec chmod u+rw,go+r {} +
    }

    validate_sample_dataset() {
        local name="$1" candidate="$2" db3 found_db3=false
        case "$name" in
            sample-map-planning|sample-map-rosbag)
                require_sample_file "$candidate/lanelet2_map.osm" || return 1
                require_sample_file "$candidate/pointcloud_map.pcd" || return 1
                ;;
            sample-rosbag)
                require_sample_file "$candidate/metadata.yaml" || return 1
                for db3 in "$candidate"/*.db3; do
                    [ -e "$db3" ] || continue
                    require_sample_file "$db3" || return 1
                    found_db3=true
                done
                if [ "$found_db3" != true ]; then
                    log_error "Sample rosbag has no nonempty DB3 file: $candidate"
                    return 1
                fi
                ;;
            kashiwanoha_map)
                require_sample_file "$candidate/lanelet2_map.osm" || return 1
                require_sample_file "$candidate/pointcloud_map.pcd" || return 1
                require_sample_file "$candidate/global_map_center.pcd.yaml" || return 1
                require_sample_file "$candidate/lanelet2_map_provider.osm.yaml" || return 1
                require_sample_file "$candidate/map.map_publisher.yaml" || return 1
                ;;
            *)
                log_error "Unknown sample dataset contract: $name"
                return 1
                ;;
        esac
    }

    validate_zip_archive() {
        local archive="$1" expected_root="$2"
        python3 - "$archive" "$expected_root" <<'PY'
import pathlib
import stat
import sys
import zipfile

archive, expected_root = sys.argv[1:]
seen = set()
with zipfile.ZipFile(archive) as source:
    for member in source.infolist():
        name = member.filename
        if not name or "\\" in name or name.startswith("/"):
            raise SystemExit(f"unsafe ZIP member: {name!r}")
        normalized = name[:-1] if name.endswith("/") else name
        parts = normalized.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise SystemExit(f"unsafe ZIP member: {name!r}")
        if parts[0] != expected_root:
            raise SystemExit(f"ZIP member outside {expected_root}: {name!r}")
        key = pathlib.PurePosixPath(*parts).as_posix()
        if key in seen:
            raise SystemExit(f"duplicate ZIP member: {name!r}")
        seen.add(key)
        if member.flag_bits & 0x1:
            raise SystemExit(f"encrypted ZIP member: {name!r}")
        file_type = (member.external_attr >> 16) & 0o170000
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise SystemExit(f"special ZIP member: {name!r}")
PY
    }

    atomic_rename_directories() {
        local candidate="$1" target="$2" flags="$3"
        python3 - "$candidate" "$target" "$flags" <<'PY'
import ctypes
import os
import sys

candidate, target = (os.fsencode(path) for path in sys.argv[1:3])
flags = int(sys.argv[3])
libc = ctypes.CDLL(None, use_errno=True)
renameat2 = libc.renameat2
renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
renameat2.restype = ctypes.c_int
if renameat2(-100, candidate, -100, target, flags) != 0:
    error = ctypes.get_errno()
    raise OSError(error, os.strerror(error))
PY
    }

    publish_sample_dataset() {
        local candidate="$1" target="$2" stage="$3"
        validate_sample_target_path "$target" || return 1
        if [ -d "$target" ]; then
            if [ "$force" != true ]; then
                log_error "Sample target appeared during installation; rerun with --force: $target"
                return 1
            fi
            if ! atomic_rename_directories "$candidate" "$target" 2; then
                log_error "Atomic replacement failed; existing dataset was left unchanged: $target"
                return 1
            fi
        else
            if ! atomic_rename_directories "$candidate" "$target" 1; then
                log_error "Atomic installation failed; no dataset was published: $target"
                return 1
            fi
        fi
        rm -rf -- "$stage"
    }

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
        local url="$1" sum="$2" name="$3" target="${MAP_ROOT}/$3" stage candidate
        validate_sample_target_path "$target" || return 1
        if [ "$force" != true ] && [ -d "$target" ]; then
            if ! validate_sample_dataset "$name" "$target"; then
                log_error "$name is incomplete at $target; rerun with --force"
                return 1
            fi
            normalize_sample_permissions "$target"
            log_info "$name already present at $target (use --force to re-download)"
            return 0
        fi
        if ! command -v unzip >/dev/null 2>&1; then
            log_error "'unzip' is required"
            return 1
        fi
        log_info "Downloading $name ..."
        curl -fL --retry 3 -o "${SAMPLE_TMP}/${name}.zip" "$url" || return 1
        sha256_verify "${SAMPLE_TMP}/${name}.zip" "$sum" || return 1
        validate_zip_archive "${SAMPLE_TMP}/${name}.zip" "$name" || return 1
        stage="$(mktemp -d "${MAP_ROOT}/.${name}.stage.XXXXXX")"
        SAMPLE_STAGE_PATHS+=("$stage")
        unzip -q "${SAMPLE_TMP}/${name}.zip" -d "$stage" || return 1
        candidate="$stage/$name"
        if [ -L "$candidate" ] || [ ! -d "$candidate" ]; then
            log_error "Archive did not create expected directory: $candidate"
            return 1
        fi
        validate_sample_dataset "$name" "$candidate" || return 1
        normalize_sample_permissions "$candidate"
        publish_sample_dataset "$candidate" "$target" "$stage" || return 1
        log_info "$name -> $target"
    }

    fetch_kashiwanoha() {
        local target="${MAP_ROOT}/kashiwanoha_map" stage candidate
        validate_sample_target_path "$target" || return 1
        if [ "$force" != true ] && [ -d "$target" ]; then
            if ! validate_sample_dataset kashiwanoha_map "$target"; then
                log_error "kashiwanoha_map is incomplete at $target; rerun with --force"
                return 1
            fi
            normalize_sample_permissions "$target"
            log_info "kashiwanoha_map already present at $target (use --force to re-download)"
            return 0
        fi
        log_info "Downloading kashiwanoha_map (tier4 scenario_simulator_v2 @ ${TIER4_SHA}) ..."
        stage="$(mktemp -d "${MAP_ROOT}/.kashiwanoha_map.stage.XXXXXX")"
        SAMPLE_STAGE_PATHS+=("$stage")
        candidate="$stage/kashiwanoha_map"
        mkdir -p "$candidate"
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
            curl -fL --retry 3 -o "${candidate}/${name}" "${TIER4_RAW}/${name}" || return 1
            sha256_verify "${candidate}/${name}" "$sum" || return 1
        done
        validate_sample_dataset kashiwanoha_map "$candidate" || return 1
        normalize_sample_permissions "$candidate"
        publish_sample_dataset "$candidate" "$target" "$stage" || return 1
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
        log_info "NOTE: logging-simulation also needs Autoware perception artifacts in ~/autoware_data"
        log_info "      (download them with: install.sh --download-artifacts)."
    }

    prepare_sample_map_root

    for fetcher in "${fetchers[@]}"; do
        "$fetcher"
    done

    log_info "Sample data downloaded to ${MAP_ROOT}."
    trap - EXIT HUP INT TERM
    remove_sample_temporary_paths
    SAMPLE_TMP=""
    SAMPLE_STAGE_PATHS=()
}

verify_installation() {
    log_info "Running post-install verification..."

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
        if nvidia_gl_libraries_present; then
            log_info "NVIDIA OpenGL/Vulkan libraries are present."
        else
            log_error "NVIDIA OpenGL/Vulkan libraries are missing (expected libnvidia-gl)."
            return 1
        fi
        log_info "Pulling NVIDIA CUDA test image for GPU verification..."
        if sudo docker pull nvidia/cuda:12.2.0-base-ubuntu22.04 &>/dev/null; then
            if sudo docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
                log_info "NVIDIA GPU runtime verification passed."
            else
                log_error "NVIDIA GPU runtime verification failed."
                return 1
            fi
        else
            log_error "Could not pull NVIDIA CUDA test image."
            return 1
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

    run_sample_data_as_target "$deployment" "$force"
    log_info "Sample data installation completed."
}

run_sample_data_as_target() {
    local deployment="$1" force="$2" script_path
    local -a command
    if [[ $EUID -ne 0 || "$TARGET_USER" == root ]]; then
        download_sample_data "$deployment" "$force"
        return
    fi
    if ! script_path=$(realpath -e -- "$0") || [[ ! -f "$script_path" ]]; then
        log_error "Sample installation under sudo requires install.sh to run from a file."
        return 1
    fi
    command=(sudo -u "$TARGET_USER" env -u SUDO_USER HOME="$USER_HOME" PATH="$PATH")
    [[ -v AUTOWARE_MAP_DIR ]] && command+=(AUTOWARE_MAP_DIR="$AUTOWARE_MAP_DIR")
    command+=(bash "$script_path" sample-data "$deployment")
    [[ "$force" == true ]] && command+=(--force)
    "${command[@]}"
}

#### Main ####
if [[ "${1:-}" == "sample-data" ]]; then
    run_sample_data_command "$@"
    exit 0
fi

parse_args "$@"
detect_host_architecture
require_sudo
check_os

install_docker

if [ "$INSTALL_NVIDIA" = true ]; then
    install_nvidia_container_toolkit
    install_nvidia_gl_libraries
fi

if [ "$INSTALL_BUILD_DEPS" = true ]; then
    install_build_dependencies
fi

if [ "$DOWNLOAD_ARTIFACTS" = true ]; then
    download_autoware_artifacts
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
