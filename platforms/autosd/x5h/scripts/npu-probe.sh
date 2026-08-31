#!/bin/sh
# npu-probe.sh — board-side proof that the NPU is actually reachable.
#
# Every layer between the device tree and the execution provider fails in a
# way that looks like the layer below it, so this checks them in order and
# names the one that broke rather than reporting "it did not work". Run it
# before spending time in the runtime.
#
# Markers: NPU_PROBE_PASS / NPU_PROBE_FAIL reason=<...>
#
# Usage: npu-probe.sh [artifacts-dir] [image]
set -u

ARTIFACTS=${1:-/root/npu/ort/sample/resnet18/resnet18_artifacts}
IMAGE=${2:-localhost/x5h-ort:1.1.0}
SCRIPT=${NPU_EVAL_SCRIPT:-/root/npu/ort/renesas_ep_eval_latency.py}

fail() { echo "NPU_PROBE_FAIL reason=$1"; exit 1; }

# --- layer 1: UIO devices bound at all ---------------------------------
# uio_pdrv_genirq binds nothing without of_id=generic-uio, and says nothing
# when it does not; an empty class directory here means x5h-uio.conf did not
# reach the image (see uio.md), not a device-tree fault.
uio_count=$(ls -d /sys/class/uio/uio* 2>/dev/null | wc -l)
[ "$uio_count" -gt 0 ] || fail uio_unbound

# --- layer 2: the NPU nodes exist in the device tree --------------------
# The names come from each node's linux,uio-name. No npuc* in sysfs means the
# NPU is not described in the booted dtb -- the udev rule cannot invent it.
npuc_sysfs=$(grep -l '^npuc' /sys/class/uio/uio*/name 2>/dev/null | wc -l)
[ "$npuc_sysfs" -ge 2 ] || fail "npuc_not_in_dtb sysfs_matches=$npuc_sysfs uio_devices=$uio_count"

# --- layer 3: udev turned those names into paths ------------------------
for d in /dev/npuc0 /dev/npuc1; do
  [ -e "$d" ] || fail "udev_symlink_missing dev=$d"
  [ -r "$d" ] && [ -w "$d" ] || fail "npuc_mode dev=$d ($(ls -l "$d"))"
done

# --- layer 3.5: the kernel is still intact ------------------------------
# Measured 2026-08-21: a run can print correct latencies on a kernel that has
# already oopsed, so a plausible number is not evidence of a healthy board.
# Two oops sources are known here, and both are worth naming rather than
# reporting as "it crashed":
#   * rcar_gen5_rproc_prepare -> of_reserved_mem_lookup, when the booted dtb
#     describes the realtime cores but not their reserved memory (the vendor
#     NPU dtb does exactly that). Stop whatever starts the realtime core.
#   * an undefined-instruction fault during model load, which takes printk
#     with it and leaves the board needing a power cycle.
# Refuse to measure on a damaged kernel; the numbers would not mean anything.
if dmesg 2>/dev/null | grep -q 'Internal error'; then
  if dmesg | grep -q 'rcar_gen5_rproc_prepare'; then
    fail "kernel_oopsed_remoteproc (dtb lacks the realtime reserved-memory nodes; disable the service that boots it)"
  fi
  fail "kernel_oopsed ($(dmesg | grep -m1 'Internal error'))"
fi

# --- layer 4: contiguous memory ----------------------------------------
# cmem0 comes from the default CMA and proves only that the module loaded.
# The runtime wants cmem_other*, which exist one per phandle in /cmem's
# memory-region list -- so their absence is a device-tree gap, not a module
# argument to tune (npu-bringup.md).
lsmod | grep -q '^cmemdrv' || fail cmem_not_loaded
ls /dev/cmem_other* >/dev/null 2>&1 || fail cmem_other_missing

# A *short count* is the trap, not a zero count. /cmem's memory-region list is
# one 4-byte phandle per region, so the expected number is knowable; and when
# one region short-changes you, the runtime fails at "Failed to open device
# /dev/cmem_otherN" -- which points at the driver, not at the real cause.
#
# The real cause, measured 2026-08-21: U-Boot's default kernel_addr_r places
# the kernel INSIDE one of the npu_region ranges. Those regions are declared
# reusable, so Linux boots and looks healthy, but cmem's whole-region
# allocation then returns -EBUSY for that one region. Load the kernel outside
# every npu_region and all of them allocate.
phandles=/proc/device-tree/cmem/memory-region
if [ -r "$phandles" ]; then
  want=$(( $(wc -c < "$phandles") / 4 ))
  have=$(ls -d /dev/cmem_other* 2>/dev/null | wc -l)
  if [ "$have" -lt "$want" ]; then
    node=$(dmesg | sed -n 's/.*assigned reserved memory node \(linux,npu_region[^ ]*\).*/\1/p' | tail -1)
    kline=$(grep -i 'kernel code' /proc/iomem 2>/dev/null | head -1)
    fail "cmem_other_short have=$have want=$want failed_node=${node:-unknown} kernel=${kline:-unknown} (is the kernel loaded inside an npu_region?)"
  fi
fi

# --- layer 5: the runtime container -------------------------------------
podman image exists "$IMAGE" || fail "image_missing image=$IMAGE"
[ -f "$SCRIPT" ] || fail "eval_script_missing path=$SCRIPT"
[ -d "$ARTIFACTS" ] || fail "artifacts_missing path=$ARTIFACTS"

# --- layer 5.5: were these artifacts actually calibrated? ----------------
# The compiling pass re-derives every internal tensor's quantization from the
# calibration dump each time it runs. Given no dump it does not refuse: it
# fabricates a histogram, quantizes everything at 1/255, and produces
# artifacts that load, run, and report entirely normal latencies. Only the
# numbers are wrong, and the sole trace is a dummy_histogram.pb left in the
# subgraph directory.
#
# That is not hypothetical -- it cost this project two days in 2026-08, and
# the wrong outputs were nearly reported to the vendor as a hardware defect.
# So name the condition here rather than letting a latency number imply the
# accuracy is meaningful.
#
# This warns and continues instead of failing: measuring latency on
# deliberately uncalibrated artifacts is legitimate (latency is independent of
# the scales, measured), and this probe's job is reachability. It is the
# accuracy claim that the marker below must not be allowed to support.
quant=real
if ls "$ARTIFACTS"/nnx/*/dummy_histogram.pb >/dev/null 2>&1; then
  quant=dummy
  echo "NPU_PROBE_WARN dummy_calibration path=$ARTIFACTS" \
       "(compiled without a calibration dump: internal scales are all 1/255," \
       "so latency is valid and every accuracy figure from these is not)"
fi

# --- layer 6: the execution provider actually ran ------------------------
# A run that merely completes proves nothing, in two separate ways. The sample
# script lists CPUExecutionProvider as a fallback, so a board with no NPU still
# produces correct results and a latency figure; and its run_inference()
# swallows every exception into a printed "Error occurred:" line and returns
# normally, so the exit status is 0 even when nothing ran. Hence three
# assertions on the output text rather than one on $?.
#
# What this does not prove is which subgraphs the NPU executed -- the provider
# list only says the EP registered. The ORT profiler (--enable-rtt) carries the
# per-node assignment; check it by hand the first time the NPU comes up, and
# turn it into an assertion here once its schema is known rather than guessed.
devs=""
for d in /dev/npuc0 /dev/npuc1 /dev/cmem_other*; do
  devs="$devs --device $d"
done
# The manifest's artifact_path is relative to the artifacts directory's PARENT
# and starts with that directory's own name ("resnet18_artifacts/nnx/..."), so
# the mount point has to keep the directory name. Mounting it as /work/artifacts
# makes the backend look for /work/resnet18_artifacts and miss.
# The manifest records where the artifacts were compiled, and it is not always
# relative. The shipped samples record a relative "resnet18_artifacts/nnx/..."
# resolved against the artifacts directory's PARENT, so the mount point must
# keep the directory name -- mounting it as /work/artifacts makes the backend
# look for /work/resnet18_artifacts and miss. Locally compiled artifacts record
# the ABSOLUTE compile-host path instead, and the backend fopen()s it verbatim,
# so there the mount point must BE that path. Read it rather than assuming.
art_name=$(basename "$ARTIFACTS")
recorded=$(sed -n 's/.*"artifact_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
             "$ARTIFACTS/nnx/manifest.json" 2>/dev/null | head -1)
case "$recorded" in
  /*) # absolute: strip the trailing /nnx/<subgraph> to get the recorded dir
      art_target=$(dirname "$(dirname "$recorded")") ;;
  "") fail "manifest_unreadable path=$ARTIFACTS/nnx/manifest.json" ;;
  *)  art_target="/work/$art_name" ;;
esac

# Device passthrough is the least-privilege form and is what this asserts. If
# the backend fails to mmap despite the nodes being present, retry by hand with
# "--privileged -v /dev:/dev", which is what the 2026-08-21 board session used;
# treat needing it as a finding worth writing down rather than a fix.
out=$(podman run --rm $devs \
        -v "$ARTIFACTS":"$art_target":ro \
        -v "$SCRIPT":/work/eval.py:ro \
        "$IMAGE" python /work/eval.py --artifacts "$art_target" 2>&1)
echo "$out"
echo "$out" | grep -q 'Error occurred:' && fail "runtime_error ($(echo "$out" | grep -m1 'Error occurred:'))"
echo "$out" | grep -q 'providers:.*RenesasExecutionProvider' || fail ep_not_selected
echo "$out" | grep -q 'avg Latency' || fail no_latency_result

# The run can complete and still have killed the kernel, so check again after.
dmesg 2>/dev/null | grep -q 'Internal error' \
  && fail "kernel_oopsed_during_run ($(dmesg | grep -m1 'Internal error'))"

echo "NPU_PROBE_PASS uio=$uio_count npuc=$npuc_sysfs cmem_other=$(ls -d /dev/cmem_other* | wc -l) quant=$quant artifacts=$art_target"
