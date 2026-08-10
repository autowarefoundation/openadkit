#!/usr/bin/env bash
# make-ufs-rootfs.sh — derive a dd-able ext4 rootfs image from the aib CI tar.
# Same reassembly the CI gate uses: xattrs must survive (capabilities,
# selinux labels), so plain `tar xf` is wrong here.
#
# The aib tar does NOT contain the rebuilt kernel's modules -- CI ships those
# as a separate modules-<release>.tar and injects them into the ext4 export as
# its own step. An image without them boots (ext4 and the essential drivers
# are built in) but silently loses everything modular: btrfs, so the container
# store cannot mount; overlay, so podman falls back; and rpmsg_client_sample,
# so the CR52 smoke fails. So this script injects them too, defaulting to the
# modules tar sitting next to the rootfs tar -- which is how they arrive when
# you download a CI run's bundle.
#
# Usage: make-ufs-rootfs.sh <x5h-rootfs.tar> <out.ext4> [size (default 6G)]
#   X5H_MODULES_TAR=<path>  override module tar autodetection
#   X5H_MODULES_TAR=none    build without modules (QEMU gate parity only)
set -euo pipefail
tar_in=$1 out=$2 size=${3:-6G}
[ -s "$tar_in" ] || { echo "FATAL: tar not found: $tar_in" >&2; exit 1; }

mod_tar=${X5H_MODULES_TAR:-$(ls "$(dirname "$tar_in")"/modules-*.tar 2>/dev/null | head -1 || true)}
if [ "$mod_tar" = none ]; then
  mod_tar=
elif [ -z "$mod_tar" ]; then
  echo "FATAL: no modules-*.tar beside $tar_in; pass X5H_MODULES_TAR=<path>," >&2
  echo "       or X5H_MODULES_TAR=none to deliberately build without modules." >&2
  exit 1
elif [ ! -s "$mod_tar" ]; then
  echo "FATAL: modules tar not found: $mod_tar" >&2; exit 1
fi

truncate -s "$size" "$out"
# -F: a rerun leaves the previous superblock in the (same-size) file and
# mkfs would stop to ask about it — this script must run unattended.
mkfs.ext4 -q -F -L x5h-root "$out"
mnt=$(mktemp -d)
trap 'sudo umount "$mnt" 2>/dev/null || true; rmdir "$mnt"' EXIT
sudo mount -o loop "$out" "$mnt"
sudo tar --xattrs --xattrs-include='*.*' -xf "$tar_in" -C "$mnt"
if [ -n "$mod_tar" ]; then
  # The modules tar roots at lib/modules/...; extract under /usr so it lands
  # in /usr/lib/modules without depending on the /lib -> usr/lib symlink.
  sudo tar -xf "$mod_tar" -C "$mnt/usr"
  echo "MODULES_INJECTED $(basename "$mod_tar")"
fi
sudo test -x "$mnt/usr/bin/podman" || { echo "FATAL: podman missing in image" >&2; exit 1; }
sudo test -x "$mnt/usr/sbin/sshd" || { echo "FATAL: sshd missing in image" >&2; exit 1; }
if [ -n "$mod_tar" ]; then
  sudo test -e "$mnt/usr/lib/modules/$(basename "$mod_tar" .tar | sed 's/^modules-//')/kernel/fs/btrfs/btrfs.ko" \
    || { echo "FATAL: btrfs.ko missing after module injection" >&2; exit 1; }
fi
sudo umount "$mnt"
echo "MAKE_UFS_ROOTFS_OK $out"
