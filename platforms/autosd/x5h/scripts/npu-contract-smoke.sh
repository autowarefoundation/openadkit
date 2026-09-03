#!/bin/sh
# On-board proof of the NPU container contract (npu role).
#   npu-contract-smoke.sh <artifacts-dir-relative-to-/opt/npu> [runs]
# Builds the ort-rootfs image if absent, runs the R3 latency harness inside it
# with exactly the device list below, and grades by output, not exit code
# (renesas_ep_eval_latency.py swallows exceptions and exits 0).
# Confirmed harness output line (R3 record, 2026-09-01):
#   Over 20 runs, avg Latency: 21.328 ms, min Latency: 20.612 ms, max Latency: 26.407 ms
# THE CONTRACT -- what a VisionPilot image gets from a board in the npu role:
#   --device /dev/uio2:/dev/npuc0 --device /dev/uio3:/dev/npuc1  (npuc* are udev
#       symlinks; podman resolves --device /dev/npuc0 to uio2 and the backend's
#       literal open("/dev/npuc1") then fails -- name the destinations)
#   --device /dev/cmem0 --device /dev/cmem_other0 ... cmem_other3
#   -v /opt/npu:/npu   (artifact sets are addressed under /npu, and compiled
#       artifacts also record absolute compile-host paths -- see npu-bringup.md)
# Markers: NPU_CONTRACT_PASS avg_ms=<v> runs=<n> image=<ref>
#          NPU_CONTRACT_FAIL reason=<wrong_role|npu_not_ready|no_image|no_artifacts|no_renesas_ep|no_latency|bad_args>
# reason= appears exactly once per marker. The no_image case narrows itself
# with detail=<no_ort_rootfs|build_failed> rather than a second reason= word,
# which any key=value grader would read as a redefinition of reason.
set -u
IMAGE=${X5H_NPU_IMAGE:-localhost/x5h-ort-rootfs:latest}
NPU=/opt/npu
ART=${1:-}; RUNS=${2:-20}
fail() { echo "NPU_CONTRACT_FAIL reason=$1"; exit 1; }
[ -n "$ART" ] || fail bad_args
[ "$(cat /run/x5h/role 2>/dev/null)" = npu ] || fail "wrong_role role=$(cat /run/x5h/role 2>/dev/null)"
systemctl is-active --quiet x5h-npu.service || fail npu_not_ready
[ -d "$NPU/$ART" ] || fail "no_artifacts path=$NPU/$ART"
if ! podman image exists "$IMAGE"; then
    [ -d "$NPU/ort-rootfs" ] || fail "no_image detail=no_ort_rootfs"
    podman build -q -t "$IMAGE" -f /usr/sbin/ort-rootfs.containerfile \
        --ignorefile /usr/sbin/ort-rootfs.containerignore "$NPU/ort-rootfs" >/dev/null || fail "no_image detail=build_failed"
fi
out=$(podman run --rm --privileged \
    --device /dev/uio2:/dev/npuc0 --device /dev/uio3:/dev/npuc1 \
    --device /dev/cmem0 --device /dev/cmem_other0 --device /dev/cmem_other1 \
    --device /dev/cmem_other2 --device /dev/cmem_other3 \
    -v "$NPU:/npu" -w /npu "$IMAGE" \
    /usr/local/bin/python3 /npu/renesas_ep_eval_latency.py --artifacts "/npu/$ART" --runs "$RUNS" 2>&1)
printf '%s\n' "$out" | grep -q RenesasExecutionProvider || { printf '%s\n' "$out" | tail -20; fail no_renesas_ep; }
avg=$(printf '%s\n' "$out" | sed -n 's/.*avg[^0-9]*\([0-9][0-9.]*\) *ms.*/\1/p' | tail -1)
[ -n "$avg" ] || { printf '%s\n' "$out" | tail -20; fail no_latency; }
echo "NPU_CONTRACT_PASS avg_ms=$avg runs=$RUNS image=$IMAGE"
