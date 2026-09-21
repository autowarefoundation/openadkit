#!/usr/bin/env bash
# make-demo-dtb.sh -- derive the demo-role device tree from the vendor NPU tree.
#
# The NPU tree drops every cr52_* reserved-memory node but leaves cr52_1's
# memory-region pointing at phandle 0x10a. Starting the core under it panics
# the vendor kernel (rcar_gen5_rproc_prepare passes the unresolved NULL to
# of_reserved_mem_lookup). This script adds the four carveouts that node needs
# and rewrites its memory-region to list all four:
#
#   cr52_ram1    2 MiB, holds the firmware's .resource_table. Index 0, because
#                rcar_gen5_rproc_prepare walks memory-region in order.
#   vdev0vring0  the two rpmsg vrings, and
#   vdev0vring1
#   vdev0buffer  the rpmsg buffer pool.
#
# The three vdev names are not decoration. rcar_gen5_rproc_prepare registers
# every memory-region phandle as a carveout NAMED AFTER THE NODE, and
# rproc_alloc_vring() and rproc_add_virtio_dev() look carveouts up by exactly
# these three names. Miss them and remoteproc falls back to
# dma_alloc_coherent() on linux,cma@40000000, which no CR52 MPU region maps, so
# the firmware data-aborts in rpmsg_init_vdev the moment it touches a vring.
# That was gate D1b on board 2, 2026-09-17.
#
# A fixed device address in the firmware's own resource table does NOT pin
# them instead: rproc_alloc_vring() matches by name, and rproc_alloc_carveout()
# only warns on an address mismatch when there is no IOMMU, then overwrites the
# firmware's value with the CMA address it allocated. The firmware therefore
# keeps FW_RSC_ADDR_ANY, which rproc_check_carveout_da() skips.
#
# 0x5da00000 and the window above it are free under the NPU role, below 4 GiB
# and outside every npu_region, so the NPU regions stay byte-identical and
# cmemdrv and the vendor host apps see no change. All four windows must sit
# inside one CR52 MPU region: see the added MPU_SetRegion() call in the safety
# island's actuation_module/freertos_x5h/vendor_patched/system_rcar_gen5.c,
# which covers 0x5da00000 for 4 MiB.
#
# no-map on every node is required, not cosmetic: rcar_gen5_rproc_mem_alloc
# maps a carveout with ioremap_wc, and arm64 refuses to ioremap memory that is
# in the linear map.
#
# Input and output are vendor blobs: run this at staging time, never commit
# either file.
#   make-demo-dtb.sh r8a78000-ironhide-npu.dtb r8a78000-ironhide-demo.dtb
set -euo pipefail
in=${1:?usage: make-demo-dtb.sh <npu.dtb> <demo.dtb>}
out=${2:?usage: make-demo-dtb.sh <npu.dtb> <demo.dtb>}
BASE=${CR52_RAM1_BASE:-0x5da00000}
SIZE=${CR52_RAM1_SIZE:-0x200000}
PH=${CR52_RAM1_PHANDLE:-0x10a}
# The three vdev windows sit in the free System RAM directly above cr52_ram1.
# 0x3000 is PAGE_ALIGN(vring_size(256, 4096)) for the 256-descriptor vrings the
# firmware's resource table declares. 0x100000 is virtio_rpmsg_bus's
# MAX_RPMSG_NUM_BUFS (512) times the patched MAX_RPMSG_BUF_SIZE (2048); the
# buffer window starts at +0x10000, not straight after vring1, to leave room
# for a larger vring without moving it.
VDEV_BASE=${CR52_VDEV_BASE:-0x5dc00000}
CR52_NODE=${CR52_NODE:-/soc/cr52_1}
for t in dtc fdtput; do
    command -v "$t" >/dev/null || { echo "FATAL: $t not installed (apt: device-tree-compiler)" >&2; exit 1; }
done
[ -r "$in" ] || { echo "FATAL: input not readable: $in" >&2; exit 1; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
dtc -q -I dtb -O dts -o "$tmp/in.dts" "$in"
if grep -q 'cr52_ram1@' "$tmp/in.dts"; then
    echo "FATAL: $in already carries cr52_ram1 (double derivation?)" >&2; exit 1
fi

# The three new phandles are allocated above the highest one the vendor tree
# already uses, not hardcoded. 0x10a is free in that tree, which is why cr52_1
# references it, but the values next to it are not: 0x10b through 0x10f are all
# live nodes. Deriving them removes the collision class rather than guarding
# against one set of constants.
maxph=0
for h in $(grep -o 'phandle = <0x[0-9a-fA-F]*>' "$tmp/in.dts" | grep -o '0x[0-9a-fA-F]*' | sort -u); do
    v=$((h))
    [ "$v" -gt "$maxph" ] && maxph=$v
done
[ "$maxph" -gt 0 ] || { echo "FATAL: no phandle found in $in; refusing to guess a free one" >&2; exit 1; }

regions="cr52_ram1 $BASE $SIZE $PH
vdev0vring0 $(printf '0x%x' $((VDEV_BASE))) 0x3000 $(printf '0x%x' $((maxph + 1)))
vdev0vring1 $(printf '0x%x' $((VDEV_BASE + 0x3000))) 0x3000 $(printf '0x%x' $((maxph + 2)))
vdev0buffer $(printf '0x%x' $((VDEV_BASE + 0x10000))) 0x100000 $(printf '0x%x' $((maxph + 3)))"

nodes=""
phandles=()
while read -r name base size ph; do
    if grep -q "phandle = <$ph>;" "$tmp/in.dts"; then
        echo "FATAL: phandle $ph is already assigned in $in; refusing to alias a live node" >&2; exit 1
    fi
    nodes+=$'\t\t'"$name@${base#0x} { reg = <0x0 $base 0x0 $size>; no-map; phandle = <$ph>; };"$'\n'
    phandles+=("$ph")
done <<<"$regions"

# Appended just inside reserved-memory's closing brace, not straight after its
# opening one: dtc refuses a tree where a subnode precedes the properties of
# the node holding it, and reserved-memory carries #address-cells, #size-cells
# and ranges. Brace depth is counted with the gsub-returns-a-count idiom.
awk -v nodes="$nodes" '
    !found && !inblock && /^[[:space:]]*reserved-memory[[:space:]]*\{/ { inblock = 1; depth = 1; print; next }
    inblock {
        depth += gsub(/\{/, "{") - gsub(/\}/, "}")
        if (depth == 0) { printf "%s", nodes; found = 1; inblock = 0 }
        print; next
    }
    { print }
    END { if (!found) exit 3 }
' "$tmp/in.dts" > "$tmp/out.dts" || { echo "FATAL: no reserved-memory node in $in" >&2; exit 1; }
dtc -q -I dts -O dtb -o "$out" "$tmp/out.dts"
# fdtput rather than a second awk pass: memory-region lives in a node this
# script does not otherwise rewrite, and dtc has already validated the tree.
# It fails loudly if $CR52_NODE is absent, which is the check we want.
fdtput -t x "$out" "$CR52_NODE" memory-region "${phandles[@]}"
echo "DEMO_DTB_OK out=$out base=$BASE size=$SIZE phandle=$PH vdev_base=$(printf '0x%x' $((VDEV_BASE))) regions=${#phandles[@]} phandles=${phandles[*]}"
