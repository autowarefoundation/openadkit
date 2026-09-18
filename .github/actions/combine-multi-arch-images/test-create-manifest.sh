#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUT="${SCRIPT_DIR}/create-manifest.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

AMD64_IMAGE='sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
ARM64_IMAGE='sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc'
ATTESTATION='sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

# Stub `docker` on PATH: `inspect --format json` succeeds iff the ref is listed
# in $PRESENT_REFS and emits an OCI index with linux/<arch> plus an attestation.
# `create` records its args to $CREATE_LOG.
cat > "${work}/docker" <<STUB
#!/usr/bin/env bash
if [ "\${1:-} \${2:-} \${3:-}" = "buildx imagetools inspect" ]; then
  ref=
  while ((\$#)); do
    case "\$1" in
      --format) shift 2; continue ;;
      buildx|imagetools|inspect) shift; continue ;;
      *) ref=\$1; shift ;;
    esac
  done
  grep -qxF "\$ref" "\${PRESENT_REFS}" || exit 1
  if [[ "\$ref" == *-amd64-* ]]; then
    arch=amd64
    image_digest=${AMD64_IMAGE}
  elif [[ "\$ref" == *-arm64-* ]]; then
    arch=arm64
    image_digest=${ARM64_IMAGE}
  else
    exit 1
  fi
  if grep -qxF "\$ref" "\${ATTESTATION_ONLY:-/dev/null}" 2>/dev/null; then
    cat <<JSON
{"manifest":{"digest":"${ATTESTATION}","manifests":[{"digest":"${ATTESTATION}","platform":{"os":"unknown","architecture":"unknown"}}]}}
JSON
    exit 0
  fi
  cat <<JSON
{"manifest":{"digest":"sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","manifests":[{"digest":"\${image_digest}","platform":{"os":"linux","architecture":"\${arch}"}},{"digest":"${ATTESTATION}","platform":{"os":"unknown","architecture":"unknown"}}]}}
JSON
  exit 0
elif [ "\${1:-} \${2:-} \${3:-}" = "buildx imagetools create" ]; then
  shift 3
  echo "create \$*" >> "\${CREATE_LOG}"
  exit 0
fi
exit 2
STUB
chmod +x "${work}/docker"
export PATH="${work}:${PATH}"
export CREATE_LOG="${work}/create.log"
export PRESENT_REFS="${work}/present.txt"
export ATTESTATION_ONLY="${work}/attestation-only.txt"
: > "${ATTESTATION_ONLY}"

fail=0
check() { if ! eval "$1"; then echo "FAIL: $1"; fail=1; fi; }
run_sut() { if env "$@" bash "${SUT}" >"${work}/out.txt" 2>&1; then rc=0; else rc=$?; fi; }

# Case 1: both arches present with attestations -> create from linux image digests only
printf '%s\n' \
  "ghcr.io/x/openadkit:planning-control-amd64-humble-T" \
  "ghcr.io/x/openadkit:planning-control-arm64-humble-T" > "${PRESENT_REFS}"
: > "${CREATE_LOG}"
run_sut IMAGE=ghcr.io/x/openadkit TARGET=planning-control ROS_DISTRO=humble ARCHES="amd64 arm64" BUILD_TAG=T
check "[ ${rc} -eq 0 ]"
check "grep -q -- '-t ghcr.io/x/openadkit:planning-control-humble-T' '${CREATE_LOG}'"
check "grep -q 'ghcr.io/x/openadkit@${AMD64_IMAGE}' '${CREATE_LOG}'"
check "grep -q 'ghcr.io/x/openadkit@${ARM64_IMAGE}' '${CREATE_LOG}'"
check "! grep -q '${ATTESTATION}' '${CREATE_LOG}'"
check "! grep -q 'planning-control-amd64-humble-T' '${CREATE_LOG}'"

# Case 2: arm64 missing -> exit 1, no create, error names the arch
printf '%s\n' "ghcr.io/x/openadkit:visualizer-amd64-humble-T" > "${PRESENT_REFS}"
: > "${CREATE_LOG}"
run_sut IMAGE=ghcr.io/x/openadkit TARGET=visualizer ROS_DISTRO=humble ARCHES="amd64 arm64" BUILD_TAG=T
check "[ ${rc} -eq 1 ]"
check "[ ! -s '${CREATE_LOG}' ]"
check "grep -q 'missing architecture' '${work}/out.txt'"
check "grep -q 'arm64' '${work}/out.txt'"

# Case 3: single arch present -> create with that linux digest
printf '%s\n' "ghcr.io/x/openadkit:carla-interface-amd64-humble-T" > "${PRESENT_REFS}"
: > "${CREATE_LOG}"
run_sut IMAGE=ghcr.io/x/openadkit TARGET=carla-interface ROS_DISTRO=humble ARCHES="amd64" BUILD_TAG=T
check "[ ${rc} -eq 0 ]"
check "grep -q 'ghcr.io/x/openadkit@${AMD64_IMAGE}' '${CREATE_LOG}'"
check "! grep -q '${ATTESTATION}' '${CREATE_LOG}'"

# Case 4: tag exists but has no linux image manifest -> fail closed, no create
printf '%s\n' "ghcr.io/x/openadkit:planning-control-amd64-humble-T" > "${PRESENT_REFS}"
printf '%s\n' "ghcr.io/x/openadkit:planning-control-amd64-humble-T" > "${ATTESTATION_ONLY}"
: > "${CREATE_LOG}"
run_sut IMAGE=ghcr.io/x/openadkit TARGET=planning-control ROS_DISTRO=humble ARCHES="amd64" BUILD_TAG=T
check "[ ${rc} -eq 1 ]"
check "[ ! -s '${CREATE_LOG}' ]"
check "grep -q 'no linux/amd64 image manifest' '${work}/out.txt'"
: > "${ATTESTATION_ONLY}"

if [ "${fail}" -eq 0 ]; then echo "create-manifest: ALL PASS"; else echo "create-manifest: TESTS FAILED"; cat "${work}/out.txt"; exit 1; fi
