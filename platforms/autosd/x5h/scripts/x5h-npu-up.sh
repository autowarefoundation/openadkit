#!/bin/sh
# Bring the NPU up in the npu role. Runs from x5h-npu.service after
# var-opt-npu.mount. Everything here was proven on board 2 (R2/R3,
# 2026-09-01): uio_pdrv_genirq autoloads with of_id=generic-uio and udev
# creates /dev/npuc0,1 unaided; only cmemdrv is manual because it is an
# out-of-tree module that lives on npu-work, not in the image.
# Markers (journal): NPU_READY uio=<n> cmem=<n> | NPU_UP_FAIL reason=<slug>
set -u
NPU=${X5H_NPU_DIR:-/opt/npu}
KO="$NPU/cmemdrv.ko"
TIMEOUT=${X5H_NPU_TIMEOUT:-20}
fail() { echo "NPU_UP_FAIL reason=$1"; exit 1; }
mountpoint -q "$NPU" || fail "npu_work_not_mounted dir=$NPU"
[ -r "$KO" ] || fail "no_cmemdrv path=$KO"
if ! grep -q '^cmemdrv ' /proc/modules; then
    insmod "$KO" || fail "insmod_failed vermagic=$(modinfo -F vermagic "$KO" 2>/dev/null | tr -d ' ') running=$(uname -r)"
fi
i=0
while [ "$i" -lt "$TIMEOUT" ]; do
    [ -e /dev/npuc0 ] && [ -e /dev/npuc1 ] && [ -e /dev/cmem0 ] && break
    i=$((i + 1)); sleep 1
done
[ -e /dev/npuc0 ] && [ -e /dev/npuc1 ] || fail "no_npuc uio_devices=$(ls /dev/uio* 2>/dev/null | wc -l)"
[ -e /dev/cmem0 ] || fail no_cmem0
cmem=$(ls /sys/class/cmem/ 2>/dev/null | grep -c '^cmem_other')
[ "$cmem" -eq 4 ] || fail "cmem_other_count=$cmem"
echo "NPU_READY uio=$(ls /dev/uio* | wc -l) cmem=$cmem"
