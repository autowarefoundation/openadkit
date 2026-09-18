#!/usr/bin/env bash
# The demo tree is the NPU tree plus the four carveout nodes cr52_1 needs, with
# its memory-region rewritten to list all four. This builds a small synthetic
# NPU-shaped tree, runs the derivation, and reads the result back with fdtget.
set -u
name=test-make-demo-dtb
here=$(cd "$(dirname "$0")" && pwd)
s="$here/../uboot/make-demo-dtb.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
command -v dtc >/dev/null || fail dtc_missing
command -v fdtget >/dev/null || fail fdtget_missing
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/npu.dts" <<'EOF'
/dts-v1/;
/ {
	#address-cells = <2>;
	#size-cells = <2>;
	reserved-memory {
		#address-cells = <2>;
		#size-cells = <2>;
		ranges;
		linux,npu_region@8e400000 {
			reg = <0x0 0x8e400000 0x0 0x31c00000>;
			no-map;
			phandle = <0x201>;
		};
	};
	soc {
		cr52_1 {
			compatible = "renesas,rcar-gen5-rproc";
			memory-region = <0x10a>;
		};
	};
};
EOF
dtc -q -I dts -O dtb -o "$tmp/npu.dtb" "$tmp/npu.dts" || fail fixture_compile
out=$(bash "$s" "$tmp/npu.dtb" "$tmp/demo.dtb") || fail derive_failed
grep -q '^DEMO_DTB_OK ' <<<"$out" || fail no_ok_marker
n=/reserved-memory/cr52_ram1@5da00000
[ "$(fdtget -t u "$tmp/demo.dtb" $n phandle)" = "266" ] || fail phandle_not_0x10a
[ "$(fdtget -t x "$tmp/demo.dtb" $n reg)" = "0 5da00000 0 200000" ] || fail reg_wrong
fdtget "$tmp/demo.dtb" $n no-map >/dev/null 2>&1 || fail no_map_missing
[ "$(fdtget -t x "$tmp/demo.dtb" /reserved-memory/linux,npu_region@8e400000 reg)" = "0 8e400000 0 31c00000" ] || fail npu_region_changed
# The three vdev nodes. Their names are what rproc_alloc_vring() and
# rproc_add_virtio_dev() look the carveouts up by, so a rename is a defect.
while read -r node want; do
    [ "$(fdtget -t x "$tmp/demo.dtb" "/reserved-memory/$node" reg)" = "$want" ] || fail "reg_wrong_$node"
    fdtget "$tmp/demo.dtb" "/reserved-memory/$node" no-map >/dev/null 2>&1 || fail "no_map_missing_$node"
done <<'EOF'
vdev0vring0@5dc00000 0 5dc00000 0 3000
vdev0vring1@5dc03000 0 5dc03000 0 3000
vdev0buffer@5dc10000 0 5dc10000 0 100000
EOF
# cr52_1 lists all four, cr52_ram1 first: rcar_gen5_rproc_prepare walks the
# list in order and rproc_add_virtio_dev falls back to index 0. The three vdev
# phandles are derived above the vendor tree's highest (0x201 here), so the
# check is the linkage, not a constant.
mr=$(fdtget -t x "$tmp/demo.dtb" /soc/cr52_1 memory-region)
[ "$mr" = "10a 202 203 204" ] || fail "cr52_ref_wrong: $mr"
i=1
for node in vdev0vring0@5dc00000 vdev0vring1@5dc03000 vdev0buffer@5dc10000; do
    ph=$(fdtget -t x "$tmp/demo.dtb" "/reserved-memory/$node" phandle)
    [ "$ph" = "$(echo "$mr" | cut -d' ' -f$((i + 1)))" ] || fail "not_linked_$node"
    i=$((i + 1))
done
# A phandle that collides with a live node must be refused, not aliased. 0x10b
# through 0x10f are live in the real vendor tree, which is why the values are
# derived rather than written down.
sed 's/phandle = <0x201>/phandle = <0x202>/' "$tmp/npu.dts" > "$tmp/collide.dts"
dtc -q -I dts -O dtb -o "$tmp/collide.dtb" "$tmp/collide.dts" || fail fixture3_compile
out=$(bash "$s" "$tmp/collide.dtb" "$tmp/c.dtb" 2>&1) || fail collision_derive_failed
mrc=$(fdtget -t x "$tmp/c.dtb" /soc/cr52_1 memory-region)
[ "$mrc" = "10a 203 204 205" ] || fail "collision_not_avoided: $mrc"
# Every window must fit the 4 MiB CR52 MPU region at 0x5da00000, or the
# firmware aborts on the first access the same way gate D1b did.
[ $((0x5dc10000 + 0x100000)) -le $((0x5da00000 + 0x400000)) ] || fail outside_mpu_region
# Refuse a tree that already assigns the phandle: aliasing a live node is worse than failing.
sed 's/phandle = <0x201>/phandle = <0x10a>/' "$tmp/npu.dts" > "$tmp/taken.dts"
dtc -q -I dts -O dtb -o "$tmp/taken.dtb" "$tmp/taken.dts" || fail fixture2_compile
bash "$s" "$tmp/taken.dtb" "$tmp/x.dtb" >/dev/null 2>&1 && fail accepts_taken_phandle
# Refuse a tree that already carries the carveout (double derivation).
bash "$s" "$tmp/demo.dtb" "$tmp/y.dtb" >/dev/null 2>&1 && fail accepts_double_derivation
echo "TEST_PASS $name"
