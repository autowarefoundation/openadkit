#!/usr/bin/env bash
# Deploy-time component-interface admission gate: the earliest point in the deploy pipeline where
# an interface mismatch across a composed image set can be caught, because it runs before any
# container in the set is created or started.
#
# Given a docker-compose file, resolve the image set it selects, then read each image's interface
# manifest(s) with NO container ever started (only `docker inspect` / `docker create` + `docker cp`
# against the image, so a binary-only third-party image works):
#
#   - Primary: the OCI label org.autoware.interface_manifest, read via `docker inspect`.
#   - Fallback: for an image with no such label, the interface_manifest_fragment.json file(s)
#     installed under /opt/autoware/share/<pkg>/ by every package that registers interfaces
#     through autoware_component_interface_utils. A container is created from the image to let
#     `docker cp` read its filesystem, but it is NEVER started -- the fallback is exactly as
#     boot-free as the label path.
#
# Either way, the SAME admission rule the runtime handshake uses (manifest_admit / evaluate_deploy)
# then runs over the whole set. A non-zero exit BLOCKS the deploy / OTA assembly BEFORE
# `docker compose up`.
#
# manifest_admit runs from a dedicated tool image (ADMIT_TOOL_IMAGE), NEVER from an image under
# test. That image's entrypoint must run manifest_admit with the ROS overlay sourced, taking the
# manifest JSON file paths as arguments and honouring manifest_admit's 0/1/2 exit-code contract --
# in particular it must reserve exit 1 for real admission verdicts and use exit 2 for its own
# failures (see test/admit-tool-entrypoint.sh next to this script for the reference tool image).
# This script does not take that on trust: an exit 1 unaccompanied by any verdict line on stdout is
# re-classified as an operational error (exit 2), so a broken tool image can never be reported as an
# interface rejection of the images under test.
#
# Usage:
#   ./deploy_check.sh <compose-file>
#   ADMIT_TOOL_IMAGE=my/admit-tool:tag ./deploy_check.sh <compose-file>
#
# Exit codes (mirrors manifest_admit):
#   0  every required interface is satisfied by a compatible provider
#   1  at least one admission rejection (MAJOR / MINOR mismatch, NO_PROVIDER, or a QOS_* verdict --
#      the endpoint's QoS differs from the QoS its spec declares, checked when --spec-manifest is
#      given) -- a TOPIC mismatch is a remap-time condition and is never seen here; it is only ever
#      raised by the runtime trigger (see the README next to this script)
#   2  operational error (`docker compose config` failed, no images, `docker inspect` failed, an
#      image has neither the label nor any installed manifest fragment or carries an unreadable one,
#      or the admission tool could not be run -- including a tool image that exits 1 without
#      emitting a single verdict line)
set -euo pipefail

COMPOSE_FILE="${1:?usage: deploy_check.sh <compose-file>}"
LABEL="org.autoware.interface_manifest"
ADMIT_TOOL_IMAGE="${ADMIT_TOOL_IMAGE:-autoware-admit-tool:jazzy}"

workdir="$(mktemp -d)"
# `cid` holds the throwaway container of the fragment fallback below, and is registered with the
# EXIT trap rather than only removed inline: `docker cp` of a multi-GB component image is the
# longest operation this script performs, and an interrupt or a CI cancellation in the middle of it
# would otherwise leak the container. It is set to "" again as soon as it has been removed inline,
# so the trap never chases an already-removed container.
cid=""
trap 'rm -rf "${workdir}"; if [ -n "${cid}" ]; then docker rm -f "${cid}" >/dev/null 2>&1 || true; fi' EXIT

# Resolve the image set the deploy config selects (no pull, no boot). `docker compose`'s own exit
# status is checked directly against a captured-to-file run, not through a pipe or process
# substitution: `set -e` only observes the last command in a pipeline, so a failing `docker compose
# config` (invalid compose YAML, a missing env_file, the daemon down, ...) piped straight into
# `mapfile` would leave `images` empty and get misreported below as "no images", masking the real
# failure. Capturing to a file first lets a `docker compose` failure surface as itself.
compose_images_file="${workdir}/compose_images.txt"
if ! docker compose -f "${COMPOSE_FILE}" config --images \
    >"${compose_images_file}" 2>"${workdir}/compose_err"; then
    echo "deploy_check: 'docker compose -f ${COMPOSE_FILE} config --images' failed" >&2
    sed 's/^/  docker compose: /' "${workdir}/compose_err" >&2
    exit 2
fi
# Pre-declare as an empty array: under `set -u`, some older bash builds leave `images` unset
# rather than empty when the process substitution produces zero lines, and the `${#images[@]}`
# check just below would then fail on an unbound variable instead of reporting "no images" cleanly.
declare -a images=()
mapfile -t images < <(sort -u "${compose_images_file}")
if [ "${#images[@]}" -eq 0 ]; then
    echo "deploy_check: no images in ${COMPOSE_FILE}" >&2
    exit 2
fi

admit_args=()
i=0
for img in "${images[@]}"; do
    echo "[deploy_check] inspecting ${img}"
    # Keep a `docker inspect` failure (image not present locally, daemon down) distinct from an
    # image that IS present but carries no label: the former is an operational error, the latter a
    # non-conformant image. Both block the deploy (exit 2) but with different diagnostics.
    if ! manifest="$(docker inspect -f "{{ index .Config.Labels \"${LABEL}\" }}" "${img}" \
        2>"${workdir}/inspect_err")"; then
        echo "deploy_check: 'docker inspect ${img}' failed — image not present locally or Docker unavailable" >&2
        sed 's/^/  docker: /' "${workdir}/inspect_err" >&2
        exit 2
    fi
    if [ -z "${manifest}" ] || [ "${manifest}" = "<no value>" ]; then
        echo "[deploy_check] ${img}: no ${LABEL} label - falling back to installed manifest fragments"
        if ! cid="$(docker create "${img}" 2>"${workdir}/create_err")"; then
            echo "deploy_check: 'docker create ${img}' failed" >&2
            sed 's/^/  docker: /' "${workdir}/create_err" >&2
            exit 2
        fi
        # The container is created but NEVER started: docker cp reads the image filesystem.
        # `docker rm -f` is deliberately non-fatal here (`|| echo ... >&2` instead of a bare call):
        # under `set -e`, an unguarded call would let a cleanup hiccup (daemon blip, container
        # already gone) abort the script with docker's own exit status instead of the 0/1/2
        # contract, and on the failure branch below it would abort BEFORE the real diagnostic ever
        # ran. A leaked throwaway container is worth a warning, never a wrong exit code.
        if ! docker cp "${cid}:/opt/autoware/share" "${workdir}/share_${i}" 2>"${workdir}/cp_err"; then
            docker rm -f "${cid}" >/dev/null 2>&1 || echo "deploy_check: warning: failed to remove throwaway container ${cid}" >&2
            cid=""
            echo "deploy_check: image ${img} has neither the ${LABEL} label nor /opt/autoware/share - not IF-versioning conformant" >&2
            exit 2
        fi
        docker rm -f "${cid}" >/dev/null 2>&1 || echo "deploy_check: warning: failed to remove throwaway container ${cid}" >&2
        cid=""
        found=0
        while IFS= read -r frag; do
            # An unreadable match must exit 2, not fall through to `cp`'s own status: the loop body
            # runs in this shell, so under `set -e` a bare `cp` failure would abort with status 1 --
            # indistinguishable, to the caller, from a real admission rejection, and with no
            # diagnostic at all. `find -name` matches by name only, so the match can be a DIRECTORY
            # called interface_manifest_fragment.json, or a symlink that `docker cp` extracted
            # dangling; both are non-conformant images, which is an operational error.
            if ! cp "${frag}" "${workdir}/manifest_${i}_${found}.json" 2>"${workdir}/frag_cp_err"; then
                echo "deploy_check: image ${img}: unreadable manifest fragment ${frag#"${workdir}/share_${i}/"}" >&2
                sed 's/^/  /' "${workdir}/frag_cp_err" >&2
                exit 2
            fi
            admit_args+=("/in/manifest_${i}_${found}.json")
            found=$((found + 1))
            # No -maxdepth here: a fragment installed one level deeper than the documented
            # share/<pkg>/interface_manifest_fragment.json path (e.g. via the CMake trap
            # install(DIRECTORY config DESTINATION share/${PROJECT_NAME}), which lands it at
            # share/<pkg>/config/interface_manifest_fragment.json instead -- see
            # autoware_component_interface_utils' README) must still be discovered. Silently missing it
            # would drop a real provider or required entry from evaluation, which can suppress a
            # NO_PROVIDER verdict the gate exists to catch; the filename is specific enough that an
            # unbounded search does not risk a false-positive collision.
        done < <(find "${workdir}/share_${i}" -name interface_manifest_fragment.json | sort)
        if [ "${found}" -eq 0 ]; then
            echo "deploy_check: image ${img} carries no interface manifest fragments" >&2
            exit 2
        fi
        echo "[deploy_check] ${img}: ${found} fragment manifest(s)"
    else
        printf '%s' "${manifest}" >"${workdir}/manifest_${i}.json"
        admit_args+=("/in/manifest_${i}.json")
    fi
    i=$((i + 1))
done

echo "[deploy_check] running admission over ${i} manifest(s) via ${ADMIT_TOOL_IMAGE} (no boot, no DDS)"
rc=0
# The tool's stdout is teed to a log as well as shown, so an exit 1 can be corroborated against the
# verdict lines that must accompany it (see below). Only stdout is redirected: the tool's stderr
# (its own warnings) still passes straight through to this script's stderr. `pipefail` is on, and
# `tee` cannot fail here, so ${rc} is the container's own status and not tee's.
tool_log="${workdir}/admit_stdout.log"
docker run --rm -v "${workdir}:/in:ro" "${ADMIT_TOOL_IMAGE}" "${admit_args[@]}" |
    tee "${tool_log}" || rc=$?

# A rejection is only believed when the tool actually printed a verdict. manifest_admit prints one
# "<consumer> <- <provider> [<interface>]: <text> (code=N)" line per verdict before returning 1, so
# an exit 1 with no such line did not come from the admission rule at all -- it is a broken or
# misbehaving tool image (a failed overlay source, a missing executable, a wrapper that exits 1 on
# its own). Reporting that as REJECTED would blame the images under test for a fault in the tool, and
# is exactly the conflation the 0/1/2 split exists to prevent, so it is re-classified as exit 2.
if [ "${rc}" -eq 1 ] && ! grep -qE '\(code=[0-9]+\)$' "${tool_log}"; then
    echo "deploy_check: the admission tool image ${ADMIT_TOOL_IMAGE} exited 1 without emitting any verdict line — treating it as an operational error, not a rejection" >&2
    exit 2
fi

case "${rc}" in
0)
    echo "[deploy_check] ACCEPTED: the composed image set is interface-compatible"
    exit 0
    ;;
1)
    echo "[deploy_check] REJECTED: incompatible interface set — blocking deploy" >&2
    exit 1
    ;;
2)
    echo "[deploy_check] operational error reported by the admission tool (exit 2)" >&2
    exit 2
    ;;
*)
    # manifest_admit only ever returns 0/1/2; any other status means the tool image itself
    # could not be run (e.g. ADMIT_TOOL_IMAGE missing) — an operational error.
    echo "deploy_check: could not run the admission tool image ${ADMIT_TOOL_IMAGE} (docker exit ${rc})" >&2
    exit 2
    ;;
esac
