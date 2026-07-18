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

if [ "${1:-}" = "env" ] && [ "${2:-}" = "LC_ALL=C" ]; then
    shift 2
fi

if [ "${1:-}" = "docker" ] && [ "${2:-}" = "info" ]; then
    if [ -f "${MOCK_NVIDIA_RUNTIME_MARKER}" ]; then
        printf '%s\n' '{"nvidia":{},"runc":{}}'
    else
        printf '%s\n' '{"runc":{}}'
    fi
    exit 0
fi

if [ "${1:-}" = "docker" ] && [ "${2:-}" = "pull" ] \
    && [[ "${3:-}" = nvidia/cuda:* ]]; then
    [ "${MOCK_CUDA_PULL_SUCCESS:-true}" = true ]
    exit $?
fi

if [ "${1:-}" = "docker" ] && [ "${2:-}" = "run" ]; then
    for argument in "$@"; do
        if [ "$argument" = "--gpus" ]; then
            [ "${MOCK_CUDA_RUN_SUCCESS:-true}" = true ]
            exit $?
        fi
    done
fi

if [ "${1:-}" = "nvidia-ctk" ] && [ "${2:-}" = "runtime" ] && [ "${3:-}" = "configure" ]; then
    touch "${MOCK_NVIDIA_RUNTIME_MARKER}"
    exit 0
fi

if [ "${1:-}" = "apt-cache" ] && [ "${2:-}" = "policy" ]; then
    printf '%s\n' '  Candidate: 5:28.0.0-1~ubuntu.22.04~jammy'
    exit 0
fi

if [ "${1:-}" = "apt-cache" ] && [ "${2:-}" = "madison" ]; then
    printf ' docker-ce | 5:28.0.0-1~ubuntu.22.04~jammy | %s jammy/stable amd64 Packages\n' \
        "${MOCK_DOCKER_CANDIDATE_ORIGIN:-https://download.docker.com/linux/ubuntu}"
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

    cat > "${case_dir}/bin/uname" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "${MOCK_ARCH:-x86_64}"
STUB

    chmod +x "${case_dir}/bin/docker" "${case_dir}/bin/sudo" \
        "${case_dir}/bin/nvidia-ctk" "${case_dir}/bin/uname"
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
        MOCK_DOCKER_CANDIDATE_ORIGIN="https://download.docker.com/linux/ubuntu" \
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
grep -q 'LC_ALL=C apt-cache policy docker-ce' "${work}/missing-compose/commands.log"
grep -q 'LC_ALL=C apt-cache madison docker-ce' "${work}/missing-compose/commands.log"
grep -q 'tee /etc/apt/sources.list.d/docker.list' "${work}/missing-compose/commands.log"
grep -q 'tee /etc/apt/preferences.d/openadkit-docker' "${work}/missing-compose/commands.log"
if grep -q 'apt-get remove' "${work}/missing-compose/commands.log"; then
    echo "FAIL: installer removed Docker packages before replacement" >&2
    exit 1
fi
candidate_line=$(grep -n 'LC_ALL=C apt-cache madison docker-ce' "${work}/missing-compose/commands.log" | cut -d: -f1)
install_line=$(grep -n 'apt-get install.*docker-ce' "${work}/missing-compose/commands.log" | cut -d: -f1)
if [ "${candidate_line}" -ge "${install_line}" ]; then
    echo "FAIL: Docker CE candidate was not validated before installation" >&2
    exit 1
fi
if grep -Fq "grep -Rqs 'download\\.docker\\.com/linux/ubuntu'" "${SUT}"; then
    echo "FAIL: installer still trusts arbitrary textual Docker repository matches" >&2
    exit 1
fi

invalid_candidate_dir="${work}/invalid-candidate"
mkdir -p "${invalid_candidate_dir}"
make_stubs "${invalid_candidate_dir}"
: > "${invalid_candidate_dir}/commands.log"
if env \
    PATH="${invalid_candidate_dir}/bin:${PATH}" \
    SUDO_USER="$(id -un)" \
    MOCK_COMMAND_LOG="${invalid_candidate_dir}/commands.log" \
    MOCK_DOCKER_INSTALLED_MARKER="${invalid_candidate_dir}/docker-installed" \
    MOCK_NVIDIA_RUNTIME_MARKER="${invalid_candidate_dir}/nvidia-runtime" \
    MOCK_COMPOSE_CAPABLE=false \
    MOCK_BUILDX_AVAILABLE=true \
    MOCK_DOCKER_CANDIDATE_ORIGIN="https://packages.example.invalid/download.docker.com/linux/ubuntu" \
    CI=true \
    OPENADKIT_CI_FORCE_DOCKER_INSTALL=false \
    bash "${SUT}" --no-nvidia > "${invalid_candidate_dir}/output.log" 2>&1; then
    echo "FAIL: installer accepted a Docker CE candidate from another repository" >&2
    exit 1
fi
grep -q 'no candidate from the configured official repository' "${invalid_candidate_dir}/output.log"
if grep -q 'apt-get install.*docker-ce' "${invalid_candidate_dir}/commands.log"; then
    echo "FAIL: installer modified Docker packages after rejecting the candidate origin" >&2
    exit 1
fi

run_case already-capable true true false
if grep -q 'docker-compose-plugin' "${work}/already-capable/commands.log"; then
    echo "FAIL: capable Docker installation was not idempotent" >&2
    exit 1
fi
grep -q 'groupadd docker' "${work}/already-capable/commands.log"
grep -q 'usermod -aG docker' "${work}/already-capable/commands.log"

unsupported_dir="${work}/unsupported-architecture"
mkdir -p "${unsupported_dir}"
make_stubs "${unsupported_dir}"
: > "${unsupported_dir}/commands.log"
if env \
    PATH="${unsupported_dir}/bin:${PATH}" \
    SUDO_USER="$(id -un)" \
    MOCK_ARCH=riscv64 \
    MOCK_COMMAND_LOG="${unsupported_dir}/commands.log" \
    MOCK_DOCKER_INSTALLED_MARKER="${unsupported_dir}/docker-installed" \
    MOCK_NVIDIA_RUNTIME_MARKER="${unsupported_dir}/nvidia-runtime" \
    MOCK_COMPOSE_CAPABLE=true \
    MOCK_BUILDX_AVAILABLE=true \
    bash "${SUT}" --no-nvidia > "${unsupported_dir}/output.log" 2>&1; then
    echo "FAIL: unsupported architecture was accepted" >&2
    exit 1
fi
grep -q 'Unsupported architecture: riscv64' "${unsupported_dir}/output.log"
if [ -s "${unsupported_dir}/commands.log" ]; then
    echo "FAIL: unsupported architecture changed host state" >&2
    cat "${unsupported_dir}/commands.log" >&2
    exit 1
fi

arm_carla_dir="${work}/arm-carla"
mkdir -p "${arm_carla_dir}"
make_stubs "${arm_carla_dir}"
: > "${arm_carla_dir}/commands.log"
if env \
    PATH="${arm_carla_dir}/bin:${PATH}" \
    SUDO_USER="$(id -un)" \
    MOCK_ARCH=aarch64 \
    MOCK_COMMAND_LOG="${arm_carla_dir}/commands.log" \
    MOCK_DOCKER_INSTALLED_MARKER="${arm_carla_dir}/docker-installed" \
    MOCK_NVIDIA_RUNTIME_MARKER="${arm_carla_dir}/nvidia-runtime" \
    MOCK_COMPOSE_CAPABLE=true \
    MOCK_BUILDX_AVAILABLE=true \
    bash "${SUT}" sample-data carla-simulation > "${arm_carla_dir}/output.log" 2>&1; then
    echo "FAIL: CARLA sample path was accepted on arm64" >&2
    exit 1
fi
grep -q 'carla-simulation requires an amd64 host' "${arm_carla_dir}/output.log"
if [ -s "${arm_carla_dir}/commands.log" ]; then
    echo "FAIL: rejected arm64 CARLA path changed host state" >&2
    exit 1
fi

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

for gpu_case in pull-failure run-failure; do
    gpu_dir="${work}/${gpu_case}"
    mkdir -p "${gpu_dir}"
    make_stubs "${gpu_dir}"
    cat > "${gpu_dir}/bin/nvidia-smi" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
    chmod +x "${gpu_dir}/bin/nvidia-smi"
    touch "${gpu_dir}/nvidia-runtime"
    : > "${gpu_dir}/commands.log"
    pull_success=true
    run_success=true
    expected_error='NVIDIA GPU runtime verification failed'
    if [ "$gpu_case" = pull-failure ]; then
        pull_success=false
        expected_error='Could not pull NVIDIA CUDA test image'
    else
        run_success=false
    fi
    if env \
        PATH="${gpu_dir}/bin:${PATH}" \
        SUDO_USER="$(id -un)" \
        MOCK_COMMAND_LOG="${gpu_dir}/commands.log" \
        MOCK_DOCKER_INSTALLED_MARKER="${gpu_dir}/docker-installed" \
        MOCK_NVIDIA_RUNTIME_MARKER="${gpu_dir}/nvidia-runtime" \
        MOCK_COMPOSE_CAPABLE=true \
        MOCK_BUILDX_AVAILABLE=true \
        MOCK_CUDA_PULL_SUCCESS="$pull_success" \
        MOCK_CUDA_RUN_SUCCESS="$run_success" \
        bash "${SUT}" --verify > "${gpu_dir}/output.log" 2>&1; then
        echo "FAIL: ${gpu_case} did not fail GPU verification" >&2
        exit 1
    fi
    grep -q "$expected_error" "${gpu_dir}/output.log"
done

sample_dir="${work}/sample-dependencies"
mkdir -p "${sample_dir}"
make_stubs "${sample_dir}"
cat > "${sample_dir}/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf 'curl' >> "${MOCK_COMMAND_LOG}"
printf ' %q' "$@" >> "${MOCK_COMMAND_LOG}"
printf '\n' >> "${MOCK_COMMAND_LOG}"
exit 1
STUB
chmod +x "${sample_dir}/bin/curl"
: > "${sample_dir}/commands.log"
if env \
    PATH="${sample_dir}/bin:${PATH}" \
    SUDO_USER="$(id -un)" \
    MOCK_COMMAND_LOG="${sample_dir}/commands.log" \
    MOCK_DOCKER_INSTALLED_MARKER="${sample_dir}/docker-installed" \
    MOCK_NVIDIA_RUNTIME_MARKER="${sample_dir}/nvidia-runtime" \
    MOCK_COMPOSE_CAPABLE=true \
    MOCK_BUILDX_AVAILABLE=true \
    AUTOWARE_MAP_DIR="${sample_dir}/maps" \
    bash "${SUT}" --no-nvidia --download-samples > "${sample_dir}/output.log" 2>&1; then
    echo "FAIL: mocked sample download unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'apt-get install -y --no-install-recommends ca-certificates curl unzip coreutils' \
    "${sample_dir}/commands.log"
dependency_line=$(grep -n 'apt-get install -y --no-install-recommends ca-certificates curl unzip coreutils' \
    "${sample_dir}/commands.log" | cut -d: -f1)
curl_line=$(grep -n '^curl ' "${sample_dir}/commands.log" | cut -d: -f1)
if [ "${dependency_line}" -ge "${curl_line}" ]; then
    echo "FAIL: sample dependencies were not installed before download" >&2
    exit 1
fi

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
