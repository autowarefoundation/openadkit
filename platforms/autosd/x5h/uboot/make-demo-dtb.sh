#!/usr/bin/env bash
# make-demo-dtb.sh -- derive the demo-role device tree from the vendor NPU tree.
#
# The NPU tree drops every cr52_* reserved-memory node but leaves cr52_1's
# memory-region pointing at phandle 0x10a. Starting the core under it panics
# the vendor kernel (rcar_gen5_rproc_prepare passes the unresolved NULL to
# of_reserved_mem_lookup). The fix is one node: a 2 MiB carveout at
# 0x5da00000, a window /proc/iomem shows free under the NPU role, below 4 GiB
# and outside every npu_region, carrying that same phandle. The NPU regions
# stay byte-identical, so cmemdrv and the vendor host apps see no change.
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
command -v dtc >/dev/null || { echo "FATAL: dtc not installed (apt: device-tree-compiler)" >&2; exit 1; }
[ -r "$in" ] || { echo "FATAL: input not readable: $in" >&2; exit 1; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
dtc -q -I dtb -O dts -o "$tmp/in.dts" "$in"
if grep -q 'cr52_ram1@' "$tmp/in.dts"; then
    echo "FATAL: $in already carries cr52_ram1 (double derivation?)" >&2; exit 1
fi
if grep -q "phandle = <$PH>;" "$tmp/in.dts"; then
    echo "FATAL: phandle $PH is already assigned in $in; refusing to alias a live node" >&2; exit 1
fi
node="cr52_ram1@${BASE#0x} { reg = <0x0 $BASE 0x0 $SIZE>; no-map; phandle = <$PH>; };"
# Appended just inside reserved-memory's closing brace, not straight after its
# opening one: dtc refuses a tree where a subnode precedes the properties of
# the node holding it, and reserved-memory carries #address-cells, #size-cells
# and ranges. Brace depth is counted with the gsub-returns-a-count idiom.
awk -v node="$node" '
    !found && !inblock && /^[[:space:]]*reserved-memory[[:space:]]*\{/ { inblock = 1; depth = 1; print; next }
    inblock {
        depth += gsub(/\{/, "{") - gsub(/\}/, "}")
        if (depth == 0) { print "\t\t" node; found = 1; inblock = 0 }
        print; next
    }
    { print }
    END { if (!found) exit 3 }
' "$tmp/in.dts" > "$tmp/out.dts" || { echo "FATAL: no reserved-memory node in $in" >&2; exit 1; }
dtc -q -I dts -O dtb -o "$out" "$tmp/out.dts"
echo "DEMO_DTB_OK out=$out base=$BASE size=$SIZE phandle=$PH"
