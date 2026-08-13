#!/usr/bin/env bash
# Copy test archives + gate-guest.sh into the ext4 export (aib add_files cannot
# write under /var, and embedding containers would dodge the unpack path under
# test), plus the rebuilt kernel's module tree and the nftables drop-in.
# Usage: inject-test-images.sh <rootfs.ext4> <testimages-dir> <kernel-bundle-dir>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOTFS="$1"; IMAGES="$2"; BUNDLE="$3"
KVER="$(cat "$BUNDLE/kernelrelease.txt")"
MNT="$(mktemp -d)"
sudo mount -o loop "$ROOTFS" "$MNT"
# The umount must actually succeed before we claim success: a failed umount
# would leave dirty pages unflushed and the loop device attached, silently
# handing a half-written export to whoever boots it next. $? is captured as
# the trap's very first statement, before any command in the trap body can
# clobber it, so the "OK" line only prints when the whole script (mount,
# copy, chmod) succeeded *and* the unmount that makes it durable succeeded.
# (st is pre-declared here only so shellcheck can see the assignment that
# actually matters, inside the trap body, below -- it has no visibility into
# variables first assigned inside a trap string.)
st=0
trap '
st=$?
sync
if ! sudo umount "$MNT"; then
    echo "FATAL: umount $MNT failed" >&2
    exit 1
fi
rmdir "$MNT"
if [ "$st" -eq 0 ]; then
    echo "OK: injected into $ROOTFS"
fi
exit "$st"
' EXIT
sudo mkdir -p "$MNT/var/lib/autosd-test"
sudo cp "$IMAGES/busybox-oci.tar" "$IMAGES/captest-docker.tar" "$IMAGES/rpmsg-eth-docker.tar" \
        "$HERE/gate-guest.sh" "$MNT/var/lib/autosd-test/"
sudo chmod +x "$MNT/var/lib/autosd-test/gate-guest.sh"

# fstab was written for a disk image and carries a LABEL=ESP entry for
# /boot/efi; the ext4 export is a bare filesystem with no ESP partition, so
# that device unit times out at boot and cascades into AutoSD's
# emergency.service ("Emergency Shell Override - Reboot") rebooting the
# guest instead of dropping to a shell. Same treatment as
# stage-nfs-rootfs.sh's board path (every fstab entry is equally wrong on
# NFS root too): preserve the original as fstab.image, ship an empty
# fstab. Safe here because the root filesystem comes from root=/dev/vda rw
# on the kernel command line, not from fstab, and systemd mounts its own
# API filesystems regardless. A missing fstab is a harmless no-op below.
if sudo test -f "$MNT/etc/fstab"; then
    sudo mv "$MNT/etc/fstab" "$MNT/etc/fstab.image"
    sudo truncate -s 0 "$MNT/etc/fstab"
fi

# The rebuilt kernel ships overlay/veth/bridge/btrfs/nf_tables as modules
# (matching the BSP kernel's shape); without this tree gate-guest.sh's
# modprobe prelude fails and every store/network gate fails confusingly.
sudo tar -xf "$BUNDLE/modules-$KVER.tar" -C "$MNT"
sudo test -d "$MNT/lib/modules/$KVER" \
    || { echo "FATAL: module tree not at /lib/modules/$KVER after extract"; exit 1; }
# depmod is arch-independent (it parses ELF metadata), so the amd64/arm64
# host can index the aarch64 modules for the guest.
sudo depmod -b "$MNT" "$KVER"
sudo test -f "$MNT/lib/modules/$KVER/modules.dep" \
    || { echo "FATAL: depmod produced no modules.dep"; exit 1; }
sudo install -D -m 0644 "$HERE/../config/60-nftables.conf" \
    "$MNT/etc/containers/containers.conf.d/60-nftables.conf"
