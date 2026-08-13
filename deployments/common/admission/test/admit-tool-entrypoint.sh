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
# The ROS / ament setup scripts reference variables that may be unset, so `set -u` is intentionally
# NOT enabled here; `set -e` still aborts on a genuine sourcing failure.
set -e

# shellcheck source=/dev/null
source /opt/ros/jazzy/setup.bash
# shellcheck source=/dev/null
source /ws/install/setup.bash

manifest_admit_args=()
if [ -f /opt/autoware/interface_manifest.json ]; then
    manifest_admit_args+=(--spec-manifest /opt/autoware/interface_manifest.json)
else
    echo "admit-tool-entrypoint: warning: no spec manifest found at /opt/autoware/interface_manifest.json - the spec QoS conformance verdict (QOS_SPEC_MISMATCH) is disabled for this run" >&2
fi

exec ros2 run autoware_component_interface_admission manifest_admit "${manifest_admit_args[@]}" "$@"
