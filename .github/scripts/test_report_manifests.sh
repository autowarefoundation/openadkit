#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUT="${SCRIPT_DIR}/report_manifests.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

cat > "${work}/docker" <<'STUB'
#!/usr/bin/env bash
if [ "$3" = "inspect" ]; then
  grep -qxF "$4" "${PRESENT_REFS}" && exit 0 || exit 1
fi
exit 2
STUB
chmod +x "${work}/docker"
export PATH="${work}:${PATH}"
export PRESENT_REFS="${work}/present.txt"
printf '%s\n' "ghcr.io/x/openadkit:planning-control-humble-T" > "${PRESENT_REFS}"

MM='{"include":[{"repo":"component","target":"planning-control","ros-distro":"humble","arches":"amd64 arm64"},{"repo":"component","target":"visualizer","ros-distro":"humble","arches":"amd64 arm64"}]}'
out=$(MANIFEST_MATRIX="${MM}" \
      IMAGE_PREFIX_COMMON=ghcr.io/x/openadkit-common \
      IMAGE_PREFIX_COMPONENT=ghcr.io/x/openadkit \
      BUILD_TAG=T bash "${SUT}")
printf '%s\n' "${out}"

fail=0
grep -q 'planning-control.*✅ created' <<< "${out}" || { echo "FAIL: created row"; fail=1; }
grep -q 'visualizer.*❌ missing'      <<< "${out}" || { echo "FAIL: missing row"; fail=1; }
if [ "${fail}" -eq 0 ]; then echo "report: ALL PASS"; else echo "report: TESTS FAILED"; exit 1; fi
