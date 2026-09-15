#!/usr/bin/env bash
# The demo tree is the NPU tree plus one carveout node carrying the phandle
# cr52_1 already references. This builds a small synthetic NPU-shaped tree,
# runs the derivation, and reads the result back with fdtget.
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
[ "$(fdtget -t u "$tmp/demo.dtb" /soc/cr52_1 memory-region)" = "266" ] || fail cr52_ref_changed
# Refuse a tree that already assigns the phandle: aliasing a live node is worse than failing.
sed 's/phandle = <0x201>/phandle = <0x10a>/' "$tmp/npu.dts" > "$tmp/taken.dts"
dtc -q -I dts -O dtb -o "$tmp/taken.dtb" "$tmp/taken.dts" || fail fixture2_compile
bash "$s" "$tmp/taken.dtb" "$tmp/x.dtb" >/dev/null 2>&1 && fail accepts_taken_phandle
# Refuse a tree that already carries the carveout (double derivation).
bash "$s" "$tmp/demo.dtb" "$tmp/y.dtb" >/dev/null 2>&1 && fail accepts_double_derivation
echo "TEST_PASS $name"
