#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUT="${SCRIPT_DIR}/create-manifest.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

# Stub `docker` on PATH: `inspect` succeeds iff the ref is listed in
# $PRESENT_REFS; `create` records its args to $CREATE_LOG.
cat > "${work}/docker" <<'STUB'
#!/usr/bin/env bash
if [ "$3" = "inspect" ]; then
  grep -qxF "$4" "${PRESENT_REFS}" && exit 0 || exit 1
elif [ "$3" = "create" ]; then
  shift 3
  echo "create $*" >> "${CREATE_LOG}"
  exit 0
fi
exit 2
STUB
chmod +x "${work}/docker"
export PATH="${work}:${PATH}"
export CREATE_LOG="${work}/create.log"
export PRESENT_REFS="${work}/present.txt"

fail=0
check() { if ! eval "$1"; then echo "FAIL: $1"; fail=1; fi; }
run_sut() { if env "$@" bash "${SUT}" >"${work}/out.txt" 2>&1; then rc=0; else rc=$?; fi; }

# Case 1: both arches present -> create with both sources, exit 0
printf '%s\n' \
  "ghcr.io/x/openadkit:planning-control-amd64-humble-T" \
  "ghcr.io/x/openadkit:planning-control-arm64-humble-T" > "${PRESENT_REFS}"
: > "${CREATE_LOG}"
run_sut IMAGE=ghcr.io/x/openadkit TARGET=planning-control ROS_DISTRO=humble ARCHES="amd64 arm64" BUILD_TAG=T
check "[ ${rc} -eq 0 ]"
check "grep -q 'planning-control-amd64-humble-T' '${CREATE_LOG}'"
check "grep -q 'planning-control-arm64-humble-T' '${CREATE_LOG}'"
check "grep -q 'ghcr.io/x/openadkit:planning-control-humble-T' '${CREATE_LOG}'"

# Case 2: arm64 missing -> exit 1, no create, error names the arch
printf '%s\n' "ghcr.io/x/openadkit:visualizer-amd64-humble-T" > "${PRESENT_REFS}"
: > "${CREATE_LOG}"
run_sut IMAGE=ghcr.io/x/openadkit TARGET=visualizer ROS_DISTRO=humble ARCHES="amd64 arm64" BUILD_TAG=T
check "[ ${rc} -eq 1 ]"
check "[ ! -s '${CREATE_LOG}' ]"
check "grep -q 'missing architecture' '${work}/out.txt'"
check "grep -q 'arm64' '${work}/out.txt'"

# Case 3: single arch present -> create with one source, exit 0
printf '%s\n' "ghcr.io/x/openadkit:carla-interface-amd64-humble-T" > "${PRESENT_REFS}"
: > "${CREATE_LOG}"
run_sut IMAGE=ghcr.io/x/openadkit TARGET=carla-interface ROS_DISTRO=humble ARCHES="amd64" BUILD_TAG=T
check "[ ${rc} -eq 0 ]"
check "grep -q 'carla-interface-amd64-humble-T' '${CREATE_LOG}'"

if [ "${fail}" -eq 0 ]; then echo "create-manifest: ALL PASS"; else echo "create-manifest: TESTS FAILED"; exit 1; fi
