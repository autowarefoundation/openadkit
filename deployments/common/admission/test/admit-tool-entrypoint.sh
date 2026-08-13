#!/usr/bin/env bash
# Entrypoint of the deploy-time admission tool image (ADMIT_TOOL_IMAGE, built by admit-tool.Dockerfile).
# Sources the ROS environment plus the admission install overlay, then runs manifest_admit over the
# manifest JSON files passed as arguments. When the tool image carries a spec manifest at
# /opt/autoware/interface_manifest.json (autoware_component_interface_specs' interface_manifest.json),
# it is prepended as --spec-manifest so spec-QoS conformance is enforced: every endpoint that carries
# QoS must use exactly the QoS its spec declares, and any deviation is a QOS_SPEC_MISMATCH rejection.
# A tool image without one still runs the version-only admission rule, but this script warns on
# stderr first, since silently dropping the QoS check is never safe for a deploy-time gate. The
# process is replaced with manifest_admit (exec), so the container exit status is manifest_admit's
# own — 0 accepted / 1 rejection / 2 operational error — which deploy_check.sh propagates verbatim.
#
# Exit 1 is therefore reserved for manifest_admit's own admission verdicts: every failure of THIS
# script exits 2 instead. Otherwise a broken tool image (an overlay that will not source, an install
# space without the executable) would exit 1 and be reported by deploy_check.sh as an interface
# rejection of the images under test, which is precisely the conflation the 0/1/2 contract exists to
# prevent. `set -e` is left on as a backstop for anything unforeseen, but every step below states its
# own exit 2 explicitly rather than relying on it.
#
# The ROS / ament setup scripts reference variables that may be unset, so `set -u` is intentionally
# NOT enabled here.
set -e

# shellcheck source=/dev/null
source /opt/ros/jazzy/setup.bash || {
    echo "admit-tool-entrypoint: cannot source /opt/ros/jazzy/setup.bash - broken tool image" >&2
    exit 2
}
# shellcheck source=/dev/null
source /ws/install/setup.bash || {
    echo "admit-tool-entrypoint: cannot source the admission overlay /ws/install/setup.bash - broken tool image" >&2
    exit 2
}

# The admission executable is installed under the package's lib directory rather than on PATH, so it
# is probed the way it will actually be invoked. Without this guard a missing executable would
# surface as `ros2 run`'s own non-zero status, which is 1.
if ! ros2 pkg executables autoware_component_interface_admission 2>/dev/null | grep -q 'manifest_admit$'; then
    echo "admit-tool-entrypoint: manifest_admit is not installed in this image's autoware_component_interface_admission overlay - broken tool image" >&2
    exit 2
fi

manifest_admit_args=()
if [ -f /opt/autoware/interface_manifest.json ]; then
    manifest_admit_args+=(--spec-manifest /opt/autoware/interface_manifest.json)
else
    echo "admit-tool-entrypoint: warning: no spec manifest found at /opt/autoware/interface_manifest.json - the spec QoS conformance verdict (QOS_SPEC_MISMATCH) is disabled for this run" >&2
fi

exec ros2 run autoware_component_interface_admission manifest_admit "${manifest_admit_args[@]}" "$@"
