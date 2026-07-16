#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../../.." && pwd)"
SUT="${REPO_ROOT}/install.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

make_stubs() {
    local case_dir="$1"
    mkdir -p "${case_dir}/bin"

    cat > "${case_dir}/bin/docker" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail

installed=false
if [ -f "${MOCK_DOCKER_INSTALLED_MARKER}" ]; then
    installed=true
fi

case "${1:-}" in
    --version)
        echo "Docker version mock"
        ;;
    compose)
        if [ "${2:-}" = "version" ]; then
            echo "v2.mock"
        elif [ "${MOCK_COMPOSE_CAPABLE}" = true ] || [ "${installed}" = true ]; then
            exit 0
        else
            exit 1
        fi
        ;;
    buildx)
        if [ "${MOCK_BUILDX_AVAILABLE}" = true ] || [ "${installed}" = true ]; then
            echo "github.com/docker/buildx mock"
        else
            exit 1
        fi
        ;;
    *)
        exit 0
        ;;
esac
STUB

    cat > "${case_dir}/bin/sudo" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail

printf 'sudo' >> "${MOCK_COMMAND_LOG}"
printf ' %q' "$@" >> "${MOCK_COMMAND_LOG}"
printf '\n' >> "${MOCK_COMMAND_LOG}"

if [ "${1:-}" = "docker" ] && [ "${2:-}" = "info" ]; then
    if [ -f "${MOCK_NVIDIA_RUNTIME_MARKER}" ]; then
        printf '%s\n' '{"nvidia":{},"runc":{}}'
    else
        printf '%s\n' '{"runc":{}}'
    fi
    exit 0
fi

if [ "${1:-}" = "nvidia-ctk" ] && [ "${2:-}" = "runtime" ] && [ "${3:-}" = "configure" ]; then
    touch "${MOCK_NVIDIA_RUNTIME_MARKER}"
    exit 0
fi

if [ "${1:-}" = "tee" ]; then
    cat > /dev/null
fi

if [ "${1:-}" = "apt-get" ] && [ "${2:-}" = "install" ]; then
    for argument in "$@"; do
        if [ "${argument}" = "docker-compose-plugin" ]; then
            touch "${MOCK_DOCKER_INSTALLED_MARKER}"
        fi
    done
fi
STUB

    cat > "${case_dir}/bin/nvidia-ctk" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "--version" ]; then
    echo "NVIDIA Container Toolkit CLI mock"
fi
STUB

    chmod +x "${case_dir}/bin/docker" "${case_dir}/bin/sudo" "${case_dir}/bin/nvidia-ctk"
}

run_case() {
    local name="$1"
    local compose_capable="$2"
    local buildx_available="$3"
    local force_install="$4"
    local case_dir="${work}/${name}"
    local target_user
    target_user="$(id -un)"
    mkdir -p "${case_dir}"
    make_stubs "${case_dir}"

    : > "${case_dir}/commands.log"
    if ! env \
        PATH="${case_dir}/bin:${PATH}" \
        SUDO_USER="${target_user}" \
        MOCK_COMMAND_LOG="${case_dir}/commands.log" \
        MOCK_DOCKER_INSTALLED_MARKER="${case_dir}/docker-installed" \
        MOCK_NVIDIA_RUNTIME_MARKER="${case_dir}/nvidia-runtime" \
        MOCK_COMPOSE_CAPABLE="${compose_capable}" \
        MOCK_BUILDX_AVAILABLE="${buildx_available}" \
        CI=true \
        OPENADKIT_CI_FORCE_DOCKER_INSTALL="${force_install}" \
        bash "${SUT}" --no-nvidia > "${case_dir}/output.log" 2>&1; then
        cat "${case_dir}/output.log" >&2
        cat "${case_dir}/commands.log" >&2
        return 1
    fi
}

run_nvidia_case() {
    local name="$1"
    local configured="$2"
    local case_dir="${work}/${name}"
    local target_user
    target_user="$(id -un)"
    mkdir -p "${case_dir}"
    make_stubs "${case_dir}"
    if [ "${configured}" = true ]; then
        touch "${case_dir}/nvidia-runtime"
    fi

    : > "${case_dir}/commands.log"
    env \
        PATH="${case_dir}/bin:${PATH}" \
        SUDO_USER="${target_user}" \
        MOCK_COMMAND_LOG="${case_dir}/commands.log" \
        MOCK_DOCKER_INSTALLED_MARKER="${case_dir}/docker-installed" \
        MOCK_NVIDIA_RUNTIME_MARKER="${case_dir}/nvidia-runtime" \
        MOCK_COMPOSE_CAPABLE=true \
        MOCK_BUILDX_AVAILABLE=true \
        CI=true \
        OPENADKIT_CI_FORCE_DOCKER_INSTALL=false \
        bash "${SUT}" > "${case_dir}/output.log" 2>&1
}

run_case missing-compose false true false
grep -q 'docker-compose-plugin' "${work}/missing-compose/commands.log"
grep -q 'usermod -aG docker' "${work}/missing-compose/commands.log"

run_case already-capable true true false
if grep -q 'docker-compose-plugin' "${work}/already-capable/commands.log"; then
    echo "FAIL: capable Docker installation was not idempotent" >&2
    exit 1
fi
grep -q 'groupadd docker' "${work}/already-capable/commands.log"
grep -q 'usermod -aG docker' "${work}/already-capable/commands.log"

run_case forced-ci-install true true true
grep -q 'docker-compose-plugin' "${work}/forced-ci-install/commands.log"
grep -q -- '--allow-change-held-packages' "${work}/forced-ci-install/commands.log"
grep -q 'Forcing official Docker package installation' "${work}/forced-ci-install/output.log"

run_nvidia_case nvidia-unconfigured false
grep -q 'nvidia-ctk runtime configure --runtime=docker' "${work}/nvidia-unconfigured/commands.log"
grep -q 'systemctl restart docker' "${work}/nvidia-unconfigured/commands.log"
grep -q 'NVIDIA Container Toolkit configured successfully' "${work}/nvidia-unconfigured/output.log"

run_nvidia_case nvidia-configured true
if grep -q 'nvidia-ctk runtime configure' "${work}/nvidia-configured/commands.log"; then
    echo "FAIL: configured NVIDIA runtime was modified" >&2
    exit 1
fi
grep -q 'NVIDIA runtime is already configured for Docker' "${work}/nvidia-configured/output.log"

rejected_dir="${work}/rejected-force"
mkdir -p "${rejected_dir}"
make_stubs "${rejected_dir}"
: > "${rejected_dir}/commands.log"
if env \
    PATH="${rejected_dir}/bin:${PATH}" \
    SUDO_USER="$(id -un)" \
    MOCK_COMMAND_LOG="${rejected_dir}/commands.log" \
    MOCK_DOCKER_INSTALLED_MARKER="${rejected_dir}/docker-installed" \
    MOCK_NVIDIA_RUNTIME_MARKER="${rejected_dir}/nvidia-runtime" \
    MOCK_COMPOSE_CAPABLE=true \
    MOCK_BUILDX_AVAILABLE=true \
    CI=false \
    OPENADKIT_CI_FORCE_DOCKER_INSTALL=true \
    bash "${SUT}" --no-nvidia > "${rejected_dir}/output.log" 2>&1; then
    echo "FAIL: force-install switch was accepted outside CI" >&2
    exit 1
fi
grep -q 'restricted to disposable CI environments' "${rejected_dir}/output.log"
if grep -q 'docker-compose-plugin' "${rejected_dir}/commands.log"; then
    echo "FAIL: rejected force-install modified Docker packages" >&2
    exit 1
fi

grep -Fq 'ansible==10.*' "${SUT}"
if grep -Fq 'ansible==6.*' "${SUT}"; then
    echo "FAIL: installer still pins Python-3.12-incompatible Ansible 6" >&2
    exit 1
fi

echo "install_docker capability tests: ALL PASS"
