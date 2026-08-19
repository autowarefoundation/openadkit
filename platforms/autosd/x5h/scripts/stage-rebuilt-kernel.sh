#!/usr/bin/env bash
# Stage the rebuilt 6.1.102-autosd kernel onto an ALREADY-STAGED AutoSD NFS
# root (stage-nfs-rootfs.sh must have completed — its stamp is checked) and
# into the TFTP directory. Strictly additive: no BSP kernel file or module
# tree is touched, so the same NFS root keeps booting under either kernel
# and rollback is one U-Boot variable away.
# Usage: stage-rebuilt-kernel.sh <staged-nfs-root> <kernel-bundle-dir> <tftp-dir>
# Run as root on the NFS server host.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$1"; BUNDLE="$2"; TFTP="$3"
[ -f "$DEST/.x5h-stage-complete" ] \
    || { echo "FATAL: $DEST has no .x5h-stage-complete stamp (run stage-nfs-rootfs.sh first)"; exit 1; }
KVER="$(cat "$BUNDLE/kernelrelease.txt")"
[ -f "$BUNDLE/Image-autosd" ] || { echo "FATAL: $BUNDLE/Image-autosd not found"; exit 1; }
[ -f "$BUNDLE/r8a78000-ironhide-uio-autosd.dtb" ] \
    || { echo "FATAL: $BUNDLE/r8a78000-ironhide-uio-autosd.dtb not found"; exit 1; }
[ -f "$BUNDLE/modules-$KVER.tar" ] || { echo "FATAL: $BUNDLE/modules-$KVER.tar not found"; exit 1; }
# The gate image and the board image share the filename Image-autosd; the
# only way to tell them apart is the embedded config. A fw-less image
# cannot NFS-netboot (MP-PHY probe fails -> rswitch defers forever -> no
# TSN link -> VFS panic) -- the exact 695106c failure mode -- so refuse it
# here, before anything reaches TFTP.
FW_LINE='CONFIG_EXTRA_FIRMWARE="rcar_gen5_mp_phy.bin"'
[ -x "$BUNDLE/extract-ikconfig" ] \
    || { echo "FATAL: $BUNDLE/extract-ikconfig missing (rebuild with the current build-bsp-kernel.sh)"; exit 1; }
# Two distinct failures, two distinct diagnostics. "No config at all" means a
# truncated/corrupt Image (or one built without CONFIG_IKCONFIG) -- reporting
# that as "built without --firmware?" would send the operator into a wrong
# 40-minute rebuild mid session, so separate the cases before judging the
# firmware line.
IKCFG="$("$BUNDLE/extract-ikconfig" "$BUNDLE/Image-autosd" || true)"
[ -n "$IKCFG" ] \
    || { echo "FATAL: extract-ikconfig recovered no embedded config from $BUNDLE/Image-autosd -- the Image is truncated, corrupt, or was not built with CONFIG_IKCONFIG. This is NOT the --firmware question: rebuilding with --firmware will not fix it. Check the file's size/sha256 against provenance.txt first."; exit 1; }
# Herestring, NOT `printf ... | grep -qxF`: under this script's `set -o
# pipefail`, `grep -q` exits the moment it matches, closing the pipe, and the
# producing `printf` then dies of SIGPIPE and reports 141. pipefail takes that
# rightmost non-zero status, so the pipeline "fails" precisely WHEN THE LINE IS
# FOUND -- a perfectly inverted guard that refused every correct board bundle
# (observed 2026-08-06, mid board session). A herestring has no pipe and no
# second process, so grep's own status is the only one there is.
grep -qxF "$FW_LINE" <<<"$IKCFG" \
    || { echo "FATAL: $BUNDLE/Image-autosd embeds a config, but not $FW_LINE (built without --firmware?) -- it cannot NFS-netboot"; exit 1; }
# tar/depmod below used to rely on bare `set -e` with no labelled diagnostic,
# unlike every other step in this file -- an operator mid-session reading a
# bare "tar: ..." or silent depmod exit deserves the same FATAL: triage cue
# the guards around them already give.
tar -xf "$BUNDLE/modules-$KVER.tar" -C "$DEST" \
    || { echo "FATAL: extracting $BUNDLE/modules-$KVER.tar into $DEST failed"; exit 1; }
[ -d "$DEST/lib/modules/$KVER" ] \
    || { echo "FATAL: module tree not at $DEST/lib/modules/$KVER after extract"; exit 1; }
# depmod is arch-independent; the x86 NFS host can index aarch64 modules.
depmod -b "$DEST" "$KVER" \
    || { echo "FATAL: depmod -b $DEST $KVER failed"; exit 1; }
[ -f "$DEST/lib/modules/$KVER/modules.dep" ] \
    || { echo "FATAL: depmod produced no modules.dep"; exit 1; }
# This drop-in is additive at the filename level but NOT neutral across
# kernels: it sets firewall_driver = "nftables", and both kernels boot this
# same NFS root (that sharing is the whole point of staging additively). The
# BSP kernel has no CONFIG_NF_TABLES, so once this file is staged, a U-Boot
# rollback to the BSP kernel alone is not enough -- it would leave the BSP
# kernel booting with a firewall driver it cannot run. See the rollback
# instruction below, which spells out the extra step.
install -D -m 0644 "$HERE/../config/60-nftables.conf" \
    "$DEST/etc/containers/containers.conf.d/60-nftables.conf"
# Refresh the test payload alongside the module tree. stage-nfs-rootfs.sh
# only ever copies board-podman-smoke.sh once, at initial staging, and
# refuses to re-run over an already-staged root -- so a board session that
# reuses a root staged before this branch would otherwise run the OLD
# script (no ext4loop mode, no rebuilt-kernel detection, no decisive
# published-port verdict, no SNAT probe) and silently prove far less than
# it looks like it does. Safe to overwrite unconditionally: the new script
# detects BSP vs rebuilt via `uname -r`, so its BSP-kernel behaviour is
# unchanged and a rollback boot still runs it correctly.
install -m 0755 "$HERE/board-podman-smoke.sh" \
    "$DEST/var/lib/autosd-test/board-podman-smoke.sh"
install -m 0644 "$BUNDLE/Image-autosd" "$TFTP/Image-autosd"
install -m 0644 "$BUNDLE/r8a78000-ironhide-uio-autosd.dtb" "$TFTP/r8a78000-ironhide-uio-autosd.dtb"
echo "OK: $KVER staged into $DEST and $TFTP"
echo "U-Boot (rebuilt): setenv kernel_file Image-autosd ; setenv dtb_file r8a78000-ironhide-uio-autosd.dtb ; setenv selinux_arg enforcing=0"
echo "U-Boot (rollback): setenv kernel_file Image ; setenv dtb_file <bsp-dtb> ; setenv selinux_arg selinux=0"
echo "  NOTE: selinux_arg expands at 'setenv bootargs_autosd' time, not at 'run' time -- after setenv'ing it, re-enter the bootargs_autosd line from uboot/autosd-boot.env before 'run bootcmd_autosd', or the old value stays baked in."
echo "Rollback ALSO needs: rm -f $DEST/etc/containers/containers.conf.d/60-nftables.conf"
echo "  (the drop-in selects the nftables driver, which the BSP kernel cannot run -- both kernels share this NFS root)"
