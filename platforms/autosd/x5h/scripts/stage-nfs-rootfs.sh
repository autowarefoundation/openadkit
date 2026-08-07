#!/usr/bin/env bash
# Stage the AutoSD tar export as an NFS root for the X5H board.
# Usage: stage-nfs-rootfs.sh <x5h-rootfs.tar> <bsp-rootfs-dir> <dest-dir> <testimages-dir>
# <bsp-rootfs-dir>: the existing BSP NFS root (source of the kernel modules).
# Run as root on the NFS server host. The BSP export is never modified.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARBALL="$1"; BSP="$2"; DEST="$3"; IMAGES="$4"
KVER=6.1.102-yocto-standard
[ -d "$BSP/lib/modules/$KVER" ] || { echo "FATAL: $BSP/lib/modules/$KVER not found"; exit 1; }
[ -e "$DEST" ] && { echo "FATAL: $DEST exists — refusing to overwrite (rm -rf it and rerun if a previous stage failed partway)"; exit 1; }
mkdir -p "$DEST"
# --xattrs: mirrors CI and the local gate replay exactly (a plain `tar xf`
# silently drops extended attributes on extract, exit 0, no warning, which
# would drop security.capability the same way it would fail GATE2/GATE3/
# GATE4 for the wrong reason there).
tar --xattrs --xattrs-include='*.*' -xf "$TARBALL" -C "$DEST"
# The BSP kernel's modules (overlayfs, veth, bridge, x_tables... are all =m).
# mkdir the destination explicitly first: GNU `cp -a src dest` copies src AS
# dest (losing the $KVER name entirely, and exiting 0) whenever dest's parent
# exists but dest itself does not -- the assert right after catches that
# instead of staging a rootfs where modprobe finds nothing.
mkdir -p "$DEST/lib/modules"
cp -a "$BSP/lib/modules/$KVER" "$DEST/lib/modules/"
[ -d "$DEST/lib/modules/$KVER" ] || { echo "FATAL: module tree not at $DEST/lib/modules/$KVER after copy"; exit 1; }
# fstab was written for a disk image; on NFS root every entry is wrong. A
# missing fstab (plausible from a podman-export-derived rootfs) is a
# harmless no-op below. An `mv` that exists but fails must abort the script:
# it is a plain statement inside this `if`'s body, not part of an `&&` list,
# so `set -e` does apply to its failure here (unlike a `[ -f x ] && mv ...`
# one-liner, where only the failure of the *last* list member is fatal).
if [ -f "$DEST/etc/fstab" ]; then
    mv "$DEST/etc/fstab" "$DEST/etc/fstab.image"
    : > "$DEST/etc/fstab"
fi
# Test payload. gate-guest.sh is deliberately NOT copied here even though
# it lives right next to board-podman-smoke.sh in this repo: it has an
# unguarded `mkfs.btrfs -f /dev/vdb` and leaves mounts stacked on
# /var/lib/containers with no cleanup -- fine for a disposable QEMU guest,
# not fine to leave sitting on the board's persistent NFS root as a second
# executable an operator listing this directory might plausibly run. The
# board has no /dev/vdb so the blast radius would be small, but shipping
# an unguarded `mkfs -f` into a session whose first invariant is "don't
# write storage" is the wrong posture regardless. Nothing on the board
# consumes gate-guest.sh; the README documents board-podman-smoke.sh only.
mkdir -p "$DEST/var/lib/autosd-test"
cp "$IMAGES/busybox-oci.tar" "$IMAGES/captest-docker.tar" \
   "$HERE/board-podman-smoke.sh" "$DEST/var/lib/autosd-test/"
chmod +x "$DEST/var/lib/autosd-test/"*.sh
# Deliberate gate/board divergence, in the safe direction, on an axis the
# QEMU gate cannot exercise at all: the gate's root is /dev/vda, so NM
# starting there (aib enables NetworkManager.service; only
# NetworkManager-wait-online.service is masked) is harmless. The board's
# root is NFS over the interface the kernel `ip=` parameter configured,
# this boot path has no initrd (uboot/autosd-boot.env loads only Image +
# DTB), so nm-initrd-generator never runs and no .nmconnection profile
# matching that static config exists anywhere in the image. NM starting on
# the NFS-root NIC with no matching profile is a classic NFS-root wedge:
# if it reconfigures the interface, root I/O stalls with no recovery --
# every binary needed to fix it lives on the filesystem that just went
# away, on a serial console, with the operator present. NM's own
# connection-assumption logic *may* leave an already-configured interface
# alone, in which case this changes nothing observable -- neither this
# script nor the gate can resolve that off-board -- but the downside is a
# dead one-shot board session and the fix is one file, so the asymmetry
# decides it. Masking (a plain symlink to /dev/null, exactly what
# `systemctl mask` itself creates, and exactly the mechanism aib already
# used for NetworkManager-wait-online.service above) rather than an
# NetworkManager conf.d "unmanaged" drop-in: masking stops the unit from
# starting at all, by any means, whereas "unmanaged" still starts NM and
# depends on its own config-parsing correctly leaving the interface alone.
# Nothing on the board needs NM -- the kernel `ip=` already configured the
# NIC, and netavark/podman0 does not depend on it (proven in the gate,
# where GATE5 passed alongside a running NM).
mkdir -p "$DEST/etc/systemd/system"
ln -sf /dev/null "$DEST/etc/systemd/system/NetworkManager.service"
# Completion stamp: $DEST existing is no longer proof staging finished (a
# partial run also leaves $DEST behind); this is.
: > "$DEST/.x5h-stage-complete"
echo "OK: staged at $DEST — now add it to /etc/exports (mirror the BSP export line) and run: exportfs -ra"
