#!/usr/bin/env bash
# Build the X5H kernel: the board's own 6.1.102 BSP source with the
# AutoSD-alignment + QEMU-gate fragments merged over the board-extracted
# config, compiled with the PINNED ARM GNU 13.2.Rel1 x86_64-hosted cross
# toolchain.
#
# Why pinned: the 2026-08-05 board session root-caused the rebuilt
# kernel's 0.09s hang to a layout-sensitive platform bug that wedges one
# secondary CPU at SMP bringup. With this exact config, GCC 13.2 booted
# 3/3 distinct layouts and GCC 13.3 wedged 3/3. The pin is EMPIRICAL, not
# a guarantee -- the board smoke stays the final arbiter for any kernel
# change (the QEMU gate cannot see this defect class). ARM ships no
# aarch64-hosted 13.2.Rel1 aarch64-none-linux-gnu toolchain (404 on both
# mirrors, verified 2026-08-05), hence x86_64 cross everywhere, CI
# included. An environment-dependent compiler fallback is exactly the
# path by which this bug returns: none is offered.
#
# Modes:
#   (default)         full build, fw-less gate image (CI / QEMU gate)
#   --firmware <dir>  full build, board image embedding rcar_gen5_mp_phy.bin
#                     from <dir> (REQUIRED for TSN netboot; NDA SDK blob --
#                     local builds only, never CI)
#   --config-only     config merge + asserts only, no compile -- but the
#                     pinned toolchain is still fetched first (Kconfig
#                     evaluates $(CC) even for config targets, and the
#                     emitted config's CONFIG_CC_VERSION_TEXT must name the
#                     compiler that will build the Image), so this mode also
#                     needs an x86_64 host
#   --toolchain-only  fetch/verify/assert the toolchain, then exit
# Usage: build-bsp-kernel.sh [--config-only|--toolchain-only] [--firmware <dir>] <outdir>
# Produces in <outdir>: Image-autosd, r8a78000-ironhide-uio-autosd.dtb,
#   modules-6.1.102-autosd.tar, kernelrelease.txt, config-autosd.txt,
#   provenance.txt, extract-ikconfig
set -euo pipefail

TOOLCHAIN_URL="https://armkeil.blob.core.windows.net/developer/Files/downloads/gnu/13.2.rel1/binrel/arm-gnu-toolchain-13.2.rel1-x86_64-aarch64-none-linux-gnu.tar.xz"
TOOLCHAIN_SHA256=12fcdf13a7430655229b20438a49e8566e26551ba08759922cdaf4695b0d4e23
TOOLCHAIN_NAME=arm-gnu-toolchain-13.2.rel1-x86_64-aarch64-none-linux-gnu
# ARM's tarball basename says "rel1" but its single top-level directory
# says "Rel1" -- two different strings, not one. The cache key and the
# download URL use the former; CROSS_COMPILE must use the latter.
TOOLCHAIN_DIRNAME=arm-gnu-toolchain-13.2.Rel1-x86_64-aarch64-none-linux-gnu
TOOLCHAIN_ID="Arm GNU Toolchain 13.2.rel1"
TOOLDIR="${X5H_TOOLCHAIN_DIR:-$HOME/.cache/x5h-toolchain}"

# Pin the umask before anything is created. modules_install installs with a
# bare `mkdir -p` + `cp` and no explicit mode (scripts/Makefile.modinst's
# cmd_install), so the module tree's permission bits -- and therefore the
# permission bytes inside modules-<kver>.tar -- follow the BUILDING
# machine's umask: 002 on this dev host, 022 on the GitHub/Ubicloud
# runners, which alone would make the tar differ across machines no matter
# what --sort/--owner/--group/--mtime do. 022 is the runner default, so
# pinning to it keeps CI's own artifacts unchanged.
umask 022

CONFIG_ONLY= TOOLCHAIN_ONLY= FWDIR=
while [ $# -gt 0 ]; do
  case "$1" in
    --config-only) CONFIG_ONLY=1; shift ;;
    --toolchain-only) TOOLCHAIN_ONLY=1; shift ;;
    --firmware)
      [ -n "${2:-}" ] || { echo "FATAL: --firmware needs a directory"; exit 1; }
      FWDIR="$(cd "$2" && pwd)"; shift 2 ;;
    *) break ;;
  esac
done
# The loop stops at the first non-flag word, so any flag written AFTER the
# positional <outdir> would otherwise be dropped in silence -- e.g.
# `build-bsp-kernel.sh ~/kernel-fw --firmware ~/fw` would quietly build a
# FIRMWARE-LESS image into a directory named for a board build, and only the
# staging guard would catch it, 30-60 minutes and one wasted rebuild later.
[ $# -le 1 ] \
  || { echo "FATAL: unexpected argument(s) after <outdir>: ${*:2} -- every flag must precede <outdir>"; exit 1; }

export ARCH=arm64
export CROSS_COMPILE="$TOOLDIR/$TOOLCHAIN_DIRNAME/bin/aarch64-none-linux-gnu-"

fetch_toolchain() {
  if [ ! -x "${CROSS_COMPILE}gcc" ]; then
    [ "$(uname -m)" = x86_64 ] \
      || { echo "FATAL: pinned toolchain is x86_64-hosted; host is $(uname -m)"; exit 1; }
    mkdir -p "$TOOLDIR"
    # Download to a scratch name and rename only on success. A partial
    # download left at the final path would satisfy the -f test on the next
    # run, so an interrupted fetch would come back as a sha256 FATAL that
    # blames verification instead of the truncated cache. In CI it is worse:
    # actions/cache saves its path even when the job fails, so one truncated
    # tarball would persist under the key and wedge every later run until the
    # key was bumped. The sha256 check below stays the authority on
    # integrity; this only stops junk from being mistaken for a cache hit.
    if [ ! -f "$TOOLDIR/$TOOLCHAIN_NAME.tar.xz" ]; then
      curl -fL "$TOOLCHAIN_URL" -o "$TOOLDIR/$TOOLCHAIN_NAME.tar.xz.part"
      mv -f "$TOOLDIR/$TOOLCHAIN_NAME.tar.xz.part" "$TOOLDIR/$TOOLCHAIN_NAME.tar.xz"
    fi
    echo "$TOOLCHAIN_SHA256  $TOOLDIR/$TOOLCHAIN_NAME.tar.xz" | sha256sum -c - \
      || { echo "FATAL: toolchain tarball failed sha256 verification"; exit 1; }
    # Keep the tarball after extraction: CI caches the tarball, not the tree.
    tar -xJf "$TOOLDIR/$TOOLCHAIN_NAME.tar.xz" -C "$TOOLDIR"
  fi
  # Capture once, then match with `case`. Two reasons, both small.
  # (1) It separates "gcc could not run at all" from "gcc ran and is the
  # wrong toolchain". The previous `gcc --version | head -1 | grep -qF`
  # form conflated them: a gcc that failed to exec made grep fail, and the
  # diagnostic then re-ran the same failing gcc to quote it, printing
  # "is not $TOOLCHAIN_ID: " with an empty version.
  # (2) It leaves no pipeline. The first line is taken with parameter
  # expansion rather than `| head -1` deliberately: under this file's
  # `set -o pipefail` an early-exiting consumer makes a producer that
  # outruns the 64 KiB pipe buffer die of SIGPIPE, and the guard then
  # returns 141 exactly when it MATCHES (the db855a4 bug). The old line
  # was safe only because `gcc --version` emits ~200 bytes -- a fact
  # invisible here, so swapping in a chattier probe (`gcc -v` dumps the
  # full specs) would silently reintroduce it. No pipeline, no trap.
  # `case` with a quoted pattern is a literal substring match, i.e. exactly
  # what grep -qF did. The `||` stays explicit: a bare assignment would
  # exit via set -e with no FATAL: line, losing the diagnostic.
  GCC_VER="$("${CROSS_COMPILE}gcc" --version)" \
    || { echo "FATAL: ${CROSS_COMPILE}gcc failed to run"; exit 1; }
  GCC_VER="${GCC_VER%%$'\n'*}"
  case "$GCC_VER" in
    *"$TOOLCHAIN_ID"*) ;;
    *) echo "FATAL: ${CROSS_COMPILE}gcc is not $TOOLCHAIN_ID: $GCC_VER"; exit 1 ;;
  esac
}

if [ -n "$TOOLCHAIN_ONLY" ]; then
  fetch_toolchain
  echo "OK (toolchain-only): $("${CROSS_COMPILE}gcc" --version | head -1)"
  exit 0
fi

[ -n "${1:-}" ] || { echo "Usage: build-bsp-kernel.sh [--config-only|--toolchain-only] [--firmware <dir>] <outdir>"; exit 1; }
OUT="$(mkdir -p "$1" && cd "$1" && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Reproducible build: same source SHA + fragments + toolchain must yield
# byte-identical artifacts on any machine, so "is this Image the same
# lineage as the CI one?" is a sha256 comparison, not artifact forensics.
# Timestamp = the pinned source commit's committer date.
export KBUILD_BUILD_TIMESTAMP="2026-04-23T08:07:21Z"
export KBUILD_BUILD_USER=openadkit
export KBUILD_BUILD_HOST=x5h
# Fetch and verify the toolchain BEFORE any `make` target runs -- config
# targets included. Linux 6.1's scripts/Kconfig.include:39 is
# `$(error-if,$(failure,command -v $(CC)),C compiler '$(CC)' not found)`,
# and CROSS_COMPILE points at an absolute path inside the EXTRACTED
# toolchain tree, so `olddefconfig` and `make -s kernelrelease` both die
# without it. CI caches only the .tar.xz, never the extracted tree, so a
# later call would be too late: every fresh runner would fail in the config
# step. Running it here also means config-autosd.txt's
# CONFIG_CC_VERSION_TEXT genuinely describes the compiler that builds the
# Image, in --config-only runs too. Do NOT "fix" a missing compiler by
# installing a distro cross-gcc instead: that would make the emitted config
# compiler-dependent, which is exactly what the pin exists to prevent.
fetch_toolchain
# Pinned commit of renesas-rcar/linux-bsp branch v6.1.102/rcar-6.0.0.rc12
# (carries r8a78000/Ironhide: the X5H). The ref is a mutable BRANCH — never
# build from the branch name. Move this SHA only deliberately, and re-run
# the QEMU gate when you do.
SHA=ff9ce02daad0f5a4e64984d725f488faf3cf3e71
SRC="$OUT/linux-bsp-$SHA"
if [ ! -d "$SRC" ]; then
  curl -fL "https://github.com/renesas-rcar/linux-bsp/archive/$SHA.tar.gz" -o "$OUT/src.tar.gz"
  tar -xzf "$OUT/src.tar.gz" -C "$OUT"     # extracts linux-bsp-<sha>/
  rm -f "$OUT/src.tar.gz"
fi
cd "$SRC"
# Path-independent build-ids, so the reproducibility promise above holds
# across build DIRECTORIES and not just across machines. The two embedded
# vDSOs and every module are linked with --build-id=sha1, and a build-id
# hashes the debug info, which records the absolute build directory in
# DW_AT_comp_dir. Building the same source under two different absolute
# paths therefore produced artifacts differing ONLY in those notes
# (measured: 40 bytes in Image-autosd, exactly 20 -- one NT_GNU_BUILD_ID --
# per .ko, 972/975 files in the tar); stripping removes the debug info but
# keeps the note, so INSTALL_MOD_STRIP does not hide it.
# Documentation/kbuild/reproducible-builds.rst prescribes exactly this map.
# -fdebug-prefix-map, NOT -ffile-prefix-map: the latter also rewrites
# __FILE__, changing .rodata contents and potentially shifting code layout
# -- and this board's SMP wedge (see the header) is layout-sensitive, with
# functionally identical kernels landing on opposite sides of it. Nothing
# here may move code; -fdebug-prefix-map affects debug info only.
#
# BOTH KCFLAGS and KAFLAGS: the kernel's top-level Makefile feeds KCFLAGS
# into KBUILD_CFLAGS and KAFLAGS into KBUILD_AFLAGS as two separate
# variables, so KCFLAGS alone leaves every .S-built object untouched.
# Measured, not assumed: KCFLAGS alone took the module tar from 972 of 975
# files differing down to 8, and all 8 survivors were arch/arm64/crypto
# modules whose C halves matched byte for byte while their .S halves did
# not (sha3-ce-glue.o same, sha3-ce-core.o differing) -- with the Image
# still differing in the two vDSOs, which are likewise part C part .S. gcc
# forwards -fdebug-prefix-map to gas as --debug-prefix-map for .S input,
# so the assembler's DWARF directory is remapped the same way; confirmed
# against the pinned 13.2.Rel1 binutils in isolation. Appended to any
# caller-supplied value rather than replacing it.
#
# $TOOLDIR is mapped as well as $SRC, because two objects' compile flags name
# the TOOLCHAIN's absolute path rather than the source tree's. Both use the
# same idiom, which exists to make <arm_neon.h> reachable from a
# -ffreestanding kernel build:
#   arch/arm64/lib/Makefile:13
#     CFLAGS_xor-neon.o += -isystem $(shell $(CC) -print-file-name=include)
#   lib/raid6/Makefile:40  (NEON_FLAGS, applied to recov_neon_inner.o)
#     NEON_FLAGS        += -isystem $(shell $(CC) -print-file-name=include)
# That expands to $TOOLDIR/<toolchain>/lib/gcc/.../include, which lands in
# the DWARF directory table of xor-neon.o and recov_neon_inner.o and hence
# in the NT_GNU_BUILD_ID of xor-neon.ko and raid6_pq.ko -- which were exactly
# the two modules of 972 that still differed between a local build under
# /home/youtalk/.cache/x5h-toolchain and a CI build under
# /home/runner/.cache/x5h-toolchain, 20 bytes each. Measured after adding
# this map: the directory entry reads /x5h/toolchain/..., those two build-ids
# moved, and Image, dtb and the other 973 tar members stayed byte-identical.
# crypto/Makefile:126 uses the same idiom for aegis128-neon-inner.o; this
# config does not build it (CONFIG_CRYPTO_AEGIS128 is not set), but the same
# map would cover it. Both maps go into both variables.
#
# raid6_pq.ko is NOT the $(AWK)/unroll.awk problem an earlier reading took it
# for (lib/raid6/Makefile:55 generates int{1,2,4,8,16,32}.c). Checked here:
# mawk 1.3.4 and busybox awk emit byte-identical int*.c, and the generated
# sources carry no host or path string. The toolchain include path above
# accounts for it. Cross-host identity of raid6_pq.ko is therefore EXPECTED
# but not yet proven -- it needs one CI artifact built with this map to
# confirm, since every local build here shares one $TOOLDIR value.
DEBUG_PREFIX_MAP="-fdebug-prefix-map=$SRC=/x5h/linux-bsp -fdebug-prefix-map=$TOOLDIR=/x5h/toolchain"
export KCFLAGS="${KCFLAGS:+$KCFLAGS }$DEBUG_PREFIX_MAP"
export KAFLAGS="${KAFLAGS:+$KAFLAGS }$DEBUG_PREFIX_MAP"
if [ -n "$FWDIR" ]; then
  [ -f "$FWDIR/rcar_gen5_mp_phy.bin" ] \
    || { echo "FATAL: $FWDIR/rcar_gen5_mp_phy.bin not found (--firmware dir must hold the SDK blob)"; exit 1; }
  mkdir -p "$SRC/firmware"
  install -m 0644 "$FWDIR/rcar_gen5_mp_phy.bin" "$SRC/firmware/"
fi
cp "$HERE/x5h-board.config" .config
if [ -n "$FWDIR" ]; then
  scripts/kconfig/merge_config.sh -m .config "$HERE/autosd.config" "$HERE/virtio.config" "$HERE/board-firmware.config"
else
  scripts/kconfig/merge_config.sh -m .config "$HERE/autosd.config" "$HERE/virtio.config"
fi
make olddefconfig
# Assert every declaration in both fragments landed. =y must be exactly =y;
# =m may legitimately resolve to =y (a select can promote it) but must not
# vanish; "is not set" must not come back enabled; quoted string values
# must match exactly. This is the same discipline the mimic-kernel build
# used, generalized to =m and string symbols.
assert_fragment() {
  frag="$1"
  while IFS= read -r line; do
    case "$line" in
      "# CONFIG_"*" is not set")
        sym="${line#\# }"; sym="${sym%% *}"
        if grep -q "^${sym}=[ym]" .config; then
          echo "FATAL: $sym enabled but $frag disables it"; exit 1
        fi ;;
      CONFIG_*=\"*\")
        grep -qF "$line" .config || { echo "FATAL: ${line%%=*} string mismatch ($frag)"; exit 1; } ;;
      CONFIG_*=y)
        grep -q "^${line}\$" .config || { echo "FATAL: ${line%%=*} not =y after merge ($frag)"; exit 1; } ;;
      CONFIG_*=m)
        sym="${line%%=*}"
        grep -q "^${sym}=[ym]" .config || { echo "FATAL: $sym neither =m nor =y after merge ($frag)"; exit 1; } ;;
    esac
  done < "$frag"
}
# board-firmware.config deliberately overrides autosd.config's
# CONFIG_EXTRA_FIRMWARE="" -- filter that one symbol out of the autosd
# assertion in firmware mode; every other declaration must land verbatim
# in both modes.
if [ -n "$FWDIR" ]; then
  grep -v '^CONFIG_EXTRA_FIRMWARE' "$HERE/autosd.config" > "$OUT/.autosd.nofw.config"
  assert_fragment "$OUT/.autosd.nofw.config"
  rm -f "$OUT/.autosd.nofw.config"
  assert_fragment "$HERE/board-firmware.config"
else
  assert_fragment "$HERE/autosd.config"
fi
assert_fragment "$HERE/virtio.config"
KVER="$(make -s kernelrelease)"
[ "$KVER" = "6.1.102-autosd" ] || { echo "FATAL: kernelrelease is $KVER, expected 6.1.102-autosd"; exit 1; }
cp .config "$OUT/config-autosd.txt"
echo "$KVER" > "$OUT/kernelrelease.txt"
if [ -n "$CONFIG_ONLY" ]; then
  echo "OK (config-only): $KVER"
  exit 0
fi
make -j"$(nproc)" Image dtbs modules
cp arch/arm64/boot/Image "$OUT/Image-autosd"
cp arch/arm64/boot/dts/renesas/r8a78000-ironhide-uio.dtb "$OUT/r8a78000-ironhide-uio-autosd.dtb"
rm -rf "$OUT/modstage"
make INSTALL_MOD_PATH="$OUT/modstage" INSTALL_MOD_STRIP=1 modules_install
# Drop the build/source symlinks (they point into this throwaway tree); the
# board and the gate want only the module tree itself.
rm -f "$OUT/modstage/lib/modules/$KVER/build" "$OUT/modstage/lib/modules/$KVER/source"
# The depmod-generated index files are deliberately EXCLUDED. modules_install
# runs the BUILDING machine's depmod, so their bytes track the host's kmod
# version rather than the kernel -- the last thing standing between this tar
# and byte-identity across machines once umask is pinned. Both consumers run
# `depmod -b <root> <kver>` immediately after extracting and then assert
# modules.dep exists (scripts/stage-rebuilt-kernel.sh for the board's NFS
# root, scripts/inject-test-images.sh for the gate's ext4 export), so the
# index is always rebuilt where it is used; anything added that extracts this
# tar must do the same or modprobe will fail. modules.order,
# modules.builtin and modules.builtin.modinfo are NOT excluded: depmod READS
# them, and they come from the build itself, so they are already
# deterministic.
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --mtime="$KBUILD_BUILD_TIMESTAMP" \
    --exclude="lib/modules/$KVER/modules.alias" \
    --exclude="lib/modules/$KVER/modules.alias.bin" \
    --exclude="lib/modules/$KVER/modules.builtin.alias.bin" \
    --exclude="lib/modules/$KVER/modules.builtin.bin" \
    --exclude="lib/modules/$KVER/modules.dep" \
    --exclude="lib/modules/$KVER/modules.dep.bin" \
    --exclude="lib/modules/$KVER/modules.devname" \
    --exclude="lib/modules/$KVER/modules.softdep" \
    --exclude="lib/modules/$KVER/modules.symbols" \
    --exclude="lib/modules/$KVER/modules.symbols.bin" \
    -C "$OUT/modstage" -cf "$OUT/modules-$KVER.tar" "lib/modules/$KVER"
rm -rf "$OUT/modstage"
# extract-ikconfig lets the staging host read the embedded config out of
# any Image without a kernel checkout (stage-rebuilt-kernel.sh uses it to
# refuse fw-less images).
install -m 0755 scripts/extract-ikconfig "$OUT/extract-ikconfig"
{
  echo "toolchain=$("${CROSS_COMPILE}gcc" --version | head -1)"
  grep '^CONFIG_EXTRA_FIRMWARE' .config
  (cd "$OUT" && sha256sum Image-autosd r8a78000-ironhide-uio-autosd.dtb "modules-$KVER.tar")
} > "$OUT/provenance.txt"
ls -lh "$OUT/Image-autosd" "$OUT/r8a78000-ironhide-uio-autosd.dtb" "$OUT/modules-$KVER.tar"
echo "OK: $KVER"
