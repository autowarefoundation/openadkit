#!/usr/bin/env bash
# Self-test for the deploy-time interface-admission gate
# (deployments/common/admission/deploy_check.sh).
#
# It resolves a dedicated ADMIT_TOOL_IMAGE that contains manifest_admit from
# autoware_component_interface_admission, builds a matrix of label-only fixture images (each
# carrying a fixture interface manifest as the OCI label org.autoware.interface_manifest), and
# asserts deploy_check.sh's exit code (and, for broken-config and the QoS rejections, its diagnostic
# output) on eleven composed image sets:
#   compatible      -> 0 (accepted)
#   incompatible    -> 1 (MAJOR mismatch)
#   no-provider     -> 1 (required interface with no provider in the set)
#   unlabeled       -> 2 (a present image lacks the conformance label AND carries no installed
#                      interface manifest fragment)
#   broken-config   -> 2 (`docker compose config` itself fails, e.g. an unset required
#                      interpolation variable — must be reported as a compose failure, not
#                      misreported as "no images")
#   fragments       -> 0 (a label-less image falls back to its installed
#                      interface_manifest_fragment.json and is still admitted)
#   qos-reject      -> 1 (a provider offers best_effort where the spec manifest baked into the tool
#                      image declares reliable. An endpoint's QoS must EQUAL the QoS its spec
#                      declares, so this is a QOS_SPEC_MISMATCH rejection — asserted by matching
#                      manifest_admit's verdict text, not just the exit code. The set holds this one
#                      publisher-only image, so no pairing exists that could produce a non-zero
#                      exit for any other reason)
#   qos-stronger    -> 1 (the same, but deviating in the STRONGER direction: transient_local where
#                      the spec declares volatile. This is the row that pins the semantics to exact
#                      matching, because a rank-based "at least as strong as" rule would ADMIT it,
#                      whereas qos-reject's weaker deviation is rejected by either rule and so
#                      cannot tell them apart. Verdict text asserted here too)
#   qos-conformant  -> 0 (the same provider with the exact QoS its spec declares: the control for
#                      both rejections above, identical to each of them but for the one field each
#                      deviates in)
#   unreadable-fragment -> 2 (the image's only fragment match is a DIRECTORY of that name, so the
#                      fragment cannot be read. An unreadable fragment is an operational error, and
#                      must not escape as `cp`'s own status 1, which would read as a rejection)
#   multi-fragment  -> 1 (one image carries two installed fragments at two different depths —
#                      one at the documented path, one nested one level deeper the way the
#                      install(DIRECTORY config ...) CMake trap would install it — and the
#                      deeper one's unmet requirement must still be caught: NO_PROVIDER)
#
# It also asserts two properties that are about the TOOL rather than the images under test:
#   * admit-tool-entrypoint.sh warns on stderr when the tool image carries no spec manifest (run
#     directly against the spec-manifest-less base image, bypassing deploy_check.sh) — the tool-side
#     half of the same no-silent-no-op requirement manifest_admit's own CLI test covers on the
#     library side.
#   * a broken tool image is an operational error (exit 2), never an interface rejection (exit 1).
#     Three separate breakages are exercised, each of which would otherwise surface as exit 1 and
#     blame the images under test for a fault in the tool.
#
# Admission tool image:
#   BASE_TOOL_IMAGE (default autoware-admit-tool:jazzy) is the plain tool image built by
#   admit-tool.Dockerfile, which carries NO spec manifest. It is reused when it already exists
#   locally (and then left in place); otherwise it is built here from CORE_REPO@CORE_REF —
#   autowarefoundation/autoware_core @ main by default. Until the admission package merges into
#   autoware_core, the default clone will not contain it and the build fails fast; point CORE_REPO /
#   CORE_REF at the branch that carries it:
#     CORE_REPO=https://github.com/<owner>/autoware_core.git CORE_REF=<branch> ./run_self_test.sh
#   The self-test then derives ADMIT_TOOL_IMAGE from it by baking in the fixture spec manifest, so
#   both the spec-QoS-enforcing and the version-only tool behaviours are exercised from one build.
#
# All images this script builds are tagged autoware-admission-self-test-* (plus BASE_TOOL_IMAGE, if
# it had to build that too) and removed on exit (best effort).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMISSION_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_CHECK="${ADMISSION_DIR}/deploy_check.sh"
FIXTURES="${SCRIPT_DIR}/fixtures"

TAG_PREFIX="autoware-admission-self-test-"
TOOL_IMAGE="${TAG_PREFIX}admit-tool"
export ADMIT_TOOL_IMAGE="${TOOL_IMAGE}"

BASE_TOOL_IMAGE="${BASE_TOOL_IMAGE:-autoware-admit-tool:jazzy}"
CORE_REPO="${CORE_REPO:-https://github.com/autowarefoundation/autoware_core.git}"
CORE_REF="${CORE_REF:-main}"

workdir="$(mktemp -d)"
built_images=()

cleanup() {
    local st=$?
    for img in "${built_images[@]:-}"; do
        [ -n "${img}" ] || continue
        docker rmi -f "${img}" >/dev/null 2>&1 || true
    done
    rm -rf "${workdir}"
    exit "${st}"
}
trap cleanup EXIT

log() { echo "[self-test] $*"; }
fail() {
    echo "[self-test] FAIL: $*" >&2
    exit 1
}

# ---- 1. Resolve the base (spec-manifest-less) admission tool image --------------------------
if docker image inspect "${BASE_TOOL_IMAGE}" >/dev/null 2>&1; then
    # Reused as-is and NOT removed on exit: it was not built here. It must be an image built by
    # admit-tool.Dockerfile, i.e. one that carries no spec manifest (step 5 asserts on that).
    log "reusing the existing base tool image ${BASE_TOOL_IMAGE}"
else
    log "building ${BASE_TOOL_IMAGE} from ${CORE_REPO}@${CORE_REF}"
    DOCKER_BUILDKIT=1 docker build \
        -t "${BASE_TOOL_IMAGE}" \
        -f "${SCRIPT_DIR}/admit-tool.Dockerfile" \
        --build-arg "CORE_REPO=${CORE_REPO}" \
        --build-arg "CORE_REF=${CORE_REF}" \
        "${SCRIPT_DIR}"
    built_images+=("${BASE_TOOL_IMAGE}")
fi

# ---- 2. Derive the spec-manifest-carrying ADMIT_TOOL_IMAGE -----------------------------------
# The fixture spec manifest is baked in so admit-tool-entrypoint.sh passes --spec-manifest and the
# spec-QoS conformance verdict is enforced. That is safe for the pre-existing cases: none of their
# fixtures carry a `qos` block, so the QoS the spec declares cannot affect them.
tool_ctx="${workdir}/tool_ctx"
mkdir -p "${tool_ctx}"
cp "${FIXTURES}/manifests/spec_manifest.json" "${tool_ctx}/interface_manifest.json"
printf 'FROM %s\nCOPY interface_manifest.json /opt/autoware/interface_manifest.json\n' \
    "${BASE_TOOL_IMAGE}" >"${tool_ctx}/Dockerfile"
log "building ${TOOL_IMAGE} (${BASE_TOOL_IMAGE} + the fixture spec manifest)"
docker build -t "${TOOL_IMAGE}" "${tool_ctx}"
built_images+=("${TOOL_IMAGE}")

# ---- 3. Build the label-only and fragment-only fixture images -------------------------------
# Each labeled image carries its fixture manifest (minified + validated) as the OCI label; the
# unlabeled image carries neither a label nor a fragment. FROM scratch keeps them empty — the gate
# only reads metadata (or, for the fragment fallback, files installed under /opt/autoware/share).
# Every fixture Dockerfile sets a placeholder CMD: `docker create` refuses an image with no command
# at all ("no command specified"), and deploy_check.sh's fragment fallback creates (never starts)
# the container to run `docker cp` against it, so a real conformant image (which always carries a
# process entrypoint) would never hit that problem, but these empty fixtures otherwise would.
build_labeled() {
    local tag="$1" manifest_json="$2" minified
    minified="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))' "${manifest_json}")"
    printf 'FROM scratch\nCMD ["true"]\n' | docker build --label "org.autoware.interface_manifest=${minified}" -t "${tag}" -
    built_images+=("${tag}")
}
build_unlabeled() {
    local tag="$1"
    printf 'FROM scratch\nCMD ["true"]\n' | docker build -t "${tag}" -
    built_images+=("${tag}")
}
# Builds an image that carries NO org.autoware.interface_manifest label, only one
# interface_manifest_fragment.json per given manifest file, installed under its own
# /opt/autoware/share/<pkg>/ directory -- the on-disk layout deploy_check.sh's fallback discovers
# when a label is absent. A real build context (not a stdin-only Dockerfile) is needed here because,
# unlike build_labeled(), files must be copied into the image.
build_fragments_image() {
    local tag="$1"
    shift
    local ctx
    ctx="$(mktemp -d "${workdir}/fragments_ctx.XXXXXX")"
    printf 'FROM scratch\nCMD ["true"]\n' >"${ctx}/Dockerfile"
    local n=0 manifest_json
    for manifest_json in "$@"; do
        mkdir -p "${ctx}/share/fixture_pkg_${n}"
        cp "${manifest_json}" "${ctx}/share/fixture_pkg_${n}/interface_manifest_fragment.json"
        echo "COPY share/fixture_pkg_${n}/interface_manifest_fragment.json /opt/autoware/share/fixture_pkg_${n}/interface_manifest_fragment.json" \
            >>"${ctx}/Dockerfile"
        n=$((n + 1))
    done
    docker build -t "${tag}" "${ctx}"
    built_images+=("${tag}")
}
# Builds a label-less image whose ONLY `find -name interface_manifest_fragment.json` match is a
# DIRECTORY of that name (`find` matches by name, so it cannot tell the two apart), which the fragment
# loop's `cp` must fail on. deploy_check.sh has to report that as an operational error rather than let
# `cp`'s own exit status 1 escape and be read by the caller as an admission rejection.
build_directory_fragment_image() {
    local tag="$1"
    local ctx
    ctx="$(mktemp -d "${workdir}/dir_fragment_ctx.XXXXXX")"
    mkdir -p "${ctx}/share/fixture_pkg_dir/interface_manifest_fragment.json"
    echo '{}' >"${ctx}/share/fixture_pkg_dir/interface_manifest_fragment.json/placeholder"
    {
        echo 'FROM scratch'
        echo 'CMD ["true"]'
        echo "COPY share/fixture_pkg_dir/interface_manifest_fragment.json/placeholder /opt/autoware/share/fixture_pkg_dir/interface_manifest_fragment.json/placeholder"
    } >"${ctx}/Dockerfile"
    docker build -t "${tag}" "${ctx}"
    built_images+=("${tag}")
}
# Builds an image carrying NO org.autoware.interface_manifest label, with two installed manifest
# fragments for two different packages at two different depths: one at the documented depth-2 path
# (share/<pkg>/interface_manifest_fragment.json) and one nested one level deeper
# (share/<pkg>/config/interface_manifest_fragment.json) -- the on-disk shape produced by the CMake
# trap install(DIRECTORY config DESTINATION share/${PROJECT_NAME}) documented (and warned against)
# in autoware_component_interface_utils' README. Exercises the same real-package-shaped multi-node /
# multi-fragment layout deploy_check.sh's fragment discovery must handle regardless of install depth.
build_multi_fragment_image() {
    local tag="$1" canonical_manifest="$2" nested_manifest="$3"
    local ctx
    ctx="$(mktemp -d "${workdir}/multi_fragment_ctx.XXXXXX")"
    mkdir -p "${ctx}/share/fixture_pkg_canonical" "${ctx}/share/fixture_pkg_nested/config"
    cp "${canonical_manifest}" "${ctx}/share/fixture_pkg_canonical/interface_manifest_fragment.json"
    cp "${nested_manifest}" "${ctx}/share/fixture_pkg_nested/config/interface_manifest_fragment.json"
    {
        echo 'FROM scratch'
        echo 'CMD ["true"]'
        echo "COPY share/fixture_pkg_canonical/interface_manifest_fragment.json /opt/autoware/share/fixture_pkg_canonical/interface_manifest_fragment.json"
        echo "COPY share/fixture_pkg_nested/config/interface_manifest_fragment.json /opt/autoware/share/fixture_pkg_nested/config/interface_manifest_fragment.json"
    } >"${ctx}/Dockerfile"
    docker build -t "${tag}" "${ctx}"
    built_images+=("${tag}")
}

build_labeled "${TAG_PREFIX}provider" "${FIXTURES}/manifests/planning_trajectory_provider.json"
build_labeled "${TAG_PREFIX}consumer-compatible" "${FIXTURES}/manifests/consumer_compatible.json"
build_labeled "${TAG_PREFIX}consumer-incompatible" "${FIXTURES}/manifests/consumer_incompatible.json"
build_labeled "${TAG_PREFIX}consumer-no-provider" "${FIXTURES}/manifests/consumer_no_provider.json"
build_labeled "${TAG_PREFIX}qos-provider-best-effort" "${FIXTURES}/manifests/qos_provider_best_effort.json"
build_labeled "${TAG_PREFIX}qos-provider-transient-local" "${FIXTURES}/manifests/qos_provider_transient_local.json"
build_labeled "${TAG_PREFIX}qos-provider-conformant" "${FIXTURES}/manifests/qos_provider_conformant.json"
build_unlabeled "${TAG_PREFIX}unlabeled"
build_fragments_image "${TAG_PREFIX}fragment-provider" "${FIXTURES}/manifests/planning_trajectory_provider.json"
build_directory_fragment_image "${TAG_PREFIX}directory-fragment"
build_multi_fragment_image "${TAG_PREFIX}multi-fragment" \
    "${FIXTURES}/manifests/planning_trajectory_provider.json" \
    "${FIXTURES}/manifests/consumer_no_provider.json"

# ---- 4. Assert deploy_check.sh exit codes ---------------------------------------------------
assert_exit() {
    local expected="$1" compose="$2" name="$3" rc=0
    echo "---- ${name} (expect exit ${expected}) ----------------------------------------------"
    "${DEPLOY_CHECK}" "${compose}" || rc=$?
    [ "${rc}" -eq "${expected}" ] || fail "${name}: expected exit ${expected}, got ${rc}"
    log "OK ${name}: deploy_check exited ${rc} as expected"
}

# Like assert_exit, but also asserts the stderr diagnostic contains BOTH ${needle} (deploy_check's
# own wrapper message) AND ${needle2} (the underlying tool's own failure signature, so the
# assertion actually proves the intended failure mode fired, not just that *some* exit-2 happened)
# and does NOT contain ${must_not_contain} — used for the broken-config case, where the exit code
# alone (2) can't tell a genuine `docker compose config` failure apart from the "no images" case it
# used to be misreported as; the message has to be checked too.
assert_exit_and_stderr() {
    local expected="$1" compose="$2" name="$3" needle="$4" needle2="$5" must_not_contain="$6" rc=0 err
    echo "---- ${name} (expect exit ${expected}, stderr containing '${needle}' and '${needle2}') ----------------------------------------------"
    err="$("${DEPLOY_CHECK}" "${compose}" 2>&1 >/dev/null)" || rc=$?
    [ "${rc}" -eq "${expected}" ] || fail "${name}: expected exit ${expected}, got ${rc}"
    echo "${err}" | grep -qF -- "${needle}" || fail "${name}: expected stderr to contain '${needle}', got: ${err}"
    echo "${err}" | grep -qF -- "${needle2}" || fail "${name}: expected stderr to contain '${needle2}', got: ${err}"
    if [ -n "${must_not_contain}" ] && echo "${err}" | grep -qF -- "${must_not_contain}"; then
        fail "${name}: stderr wrongly contains '${must_not_contain}' (misdiagnosed), got: ${err}"
    fi
    log "OK ${name}: deploy_check exited ${rc} with the expected diagnostic"
}

# Like assert_exit, but also asserts the combined stdout+stderr output contains ${needle} -- used
# for a case whose exit code alone has more than one structurally possible cause, where the point
# of the assertion is to pin the failure down to the ONE verdict this case exists to exercise.
# manifest_admit prints its per-endpoint / per-pairing verdict lines (e.g. the QOS_SPEC_MISMATCH
# text) to its own stdout, not stderr (see manifest_admit_cli.cpp / manifest_admit.cpp in
# autoware_component_interface_admission), and deploy_check.sh never separates that from its own
# stdout, so stdout has to be captured too -- unlike assert_exit_and_stderr, which only ever needs
# deploy_check.sh's own wrapper messages on stderr.
assert_exit_and_output() {
    local expected="$1" compose="$2" name="$3" needle="$4" rc=0 combined
    echo "---- ${name} (expect exit ${expected}, output containing '${needle}') ----------------------------------------------"
    combined="$("${DEPLOY_CHECK}" "${compose}" 2>&1)" || rc=$?
    [ "${rc}" -eq "${expected}" ] || fail "${name}: expected exit ${expected}, got ${rc}"
    echo "${combined}" | grep -qF -- "${needle}" ||
        fail "${name}: expected output to contain '${needle}', got: ${combined}"
    log "OK ${name}: deploy_check exited ${rc} with the expected verdict in its output"
}

assert_exit 0 "${FIXTURES}/compose/compose.compatible.yaml" "compatible-set"
assert_exit 1 "${FIXTURES}/compose/compose.incompatible.yaml" "incompatible-set"
assert_exit 1 "${FIXTURES}/compose/compose.no-provider.yaml" "no-provider-set"
assert_exit 2 "${FIXTURES}/compose/compose.unlabeled.yaml" "unlabeled-image"
assert_exit_and_stderr 2 "${FIXTURES}/compose/compose.broken-config.yaml" "broken-config" \
    "docker compose -f" "DEPLOY_CHECK_SELF_TEST_MUST_BE_SET" "no images in"
assert_exit 0 "${FIXTURES}/compose/compose.fragments.yaml" "fragments"
assert_exit_and_output 2 "${FIXTURES}/compose/compose.unreadable-fragment.yaml" "unreadable-fragment" \
    "unreadable manifest fragment"
assert_exit_and_output 1 "${FIXTURES}/compose/compose.qos-reject.yaml" "qos-reject" \
    "QOS mismatch: endpoint QoS differs from the QoS its spec declares"
assert_exit_and_output 1 "${FIXTURES}/compose/compose.qos-stronger.yaml" "qos-stronger" \
    "QOS mismatch: endpoint QoS differs from the QoS its spec declares"
assert_exit 0 "${FIXTURES}/compose/compose.qos-conformant.yaml" "qos-conformant"
assert_exit 1 "${FIXTURES}/compose/compose.multi-fragment.yaml" "multi-fragment-image"

# ---- 5. Assert admit-tool-entrypoint.sh's own no-spec-manifest warning -----------------------
# Run the spec-manifest-less base tool image directly (bypassing deploy_check.sh) against a plain
# fixture manifest, the same way deploy_check.sh itself invokes ADMIT_TOOL_IMAGE (workdir mounted
# read-only at /in, manifest paths passed as positional arguments).
echo "---- no-spec-manifest tool warning (expect stderr containing 'no spec manifest') ----------------------------------------------"
no_spec_in_dir="$(mktemp -d "${workdir}/no_spec_in.XXXXXX")"
cp "${FIXTURES}/manifests/planning_trajectory_provider.json" "${no_spec_in_dir}/manifest.json"
no_spec_err="$(docker run --rm -v "${no_spec_in_dir}:/in:ro" "${BASE_TOOL_IMAGE}" /in/manifest.json 2>&1 >/dev/null)" || true
echo "${no_spec_err}" | grep -qF -- "no spec manifest" ||
    fail "no-spec-manifest tool warning: expected stderr to contain 'no spec manifest', got: ${no_spec_err}"
log "OK no-spec-manifest tool warning: admit-tool-entrypoint.sh warned as expected"

# ---- 6. Assert a broken tool image is an operational error, never a rejection -----------------
# A fault in the tool must never be reported as an interface rejection of the images under test: exit
# 1 means "these images are incompatible", and a deploy pipeline acts on that. Each breakage below
# would produce exit 1 without the guards it exercises — the entrypoint's own `|| exit 2` on each
# source, its executable probe, and deploy_check.sh's requirement that an exit 1 be accompanied by at
# least one verdict line (the last of which is what protects the contract for a foreign tool image
# that does not use this entrypoint at all). Every case runs against compose.compatible.yaml, whose
# only correct verdicts are ACCEPTED, so a wrong exit 1 could not come from the fixtures.
build_derived_tool_image() {
    local tag="$1" body="$2"
    printf 'FROM %s\n%s\n' "${TOOL_IMAGE}" "${body}" | docker build -t "${tag}" -
    built_images+=("${tag}")
}

assert_broken_tool_is_operational_error() {
    local tag="$1" name="$2" needle="$3" rc=0 combined
    echo "---- ${name} (expect exit 2, output containing '${needle}') ----------------------------------------------"
    combined="$(ADMIT_TOOL_IMAGE="${tag}" "${DEPLOY_CHECK}" \
        "${FIXTURES}/compose/compose.compatible.yaml" 2>&1)" || rc=$?
    [ "${rc}" -eq 2 ] || fail "${name}: expected exit 2 (operational error), got ${rc}"
    echo "${combined}" | grep -qF -- "${needle}" ||
        fail "${name}: expected output to contain '${needle}', got: ${combined}"
    log "OK ${name}: a broken tool image exited 2, not 1"
}

build_derived_tool_image "${TAG_PREFIX}admit-tool-no-overlay" 'RUN rm -f /ws/install/setup.bash'
assert_broken_tool_is_operational_error "${TAG_PREFIX}admit-tool-no-overlay" \
    "broken-tool-unsourceable-overlay" "cannot source the admission overlay"

build_derived_tool_image "${TAG_PREFIX}admit-tool-no-executable" \
    'RUN find /ws/install -name manifest_admit -type f -delete'
assert_broken_tool_is_operational_error "${TAG_PREFIX}admit-tool-no-executable" \
    "broken-tool-missing-executable" "manifest_admit is not installed"

# A tool image that says nothing and exits 1 — the foreign / non-conforming tool image case, caught by
# deploy_check.sh itself rather than by anything in admit-tool-entrypoint.sh.
build_derived_tool_image "${TAG_PREFIX}admit-tool-silent-failure" \
    'ENTRYPOINT ["/bin/sh", "-c", "exit 1"]'
assert_broken_tool_is_operational_error "${TAG_PREFIX}admit-tool-silent-failure" \
    "broken-tool-silent-exit-1" "exited 1 without emitting any verdict line"

log "ALL ASSERTIONS PASSED"
