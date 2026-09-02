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
# osbuild never runs `systemctl preset`, so the preset file describes
# symlinks nobody created. Create them here from the preset itself, so the
# preset stays the one place that says what is enabled.
preset="$mnt/etc/systemd/system-preset/80-x5h.preset"
sudo test -r "$preset" || { echo "FATAL: $preset missing in image" >&2; exit 1; }
# Capture the preset lines before the loop. `sudo grep ... | while` dies
# SILENTLY under `set -euo pipefail` when the preset has zero `enable ` lines:
# grep exits 1, pipefail promotes that to the pipeline status, and the script
# stops with no message at all -- the one silent failure on a path where every
# other check is loud, and the resulting image would boot with none of the X5H
# units enabled.
preset_rc=0
enables=$(sudo grep '^enable ' "$preset") || preset_rc=$?
if [ "$preset_rc" -ne 0 ]; then
  echo "FATAL: no 'enable ' lines in $preset (grep exit $preset_rc); the image" >&2
  echo "       would boot with none of the X5H units enabled" >&2
  exit 1
fi
printf '%s\n' "$enables" | while read -r _ unit; do
  src=""
  for d in /etc/systemd/system /usr/lib/systemd/system; do
    sudo test -f "$mnt$d/$unit" && { src="$d/$unit"; break; }
  done
  [ -n "$src" ] || { echo "FATAL: preset enables $unit but the image has no such unit" >&2; exit 1; }
  target=$(sudo sed -n 's/^WantedBy=//p' "$mnt$src" | head -1)
  [ -n "$target" ] || { echo "FATAL: $unit has no [Install] WantedBy=" >&2; exit 1; }
  sudo mkdir -p "$mnt/etc/systemd/system/$target.wants"
  sudo ln -sfn "$src" "$mnt/etc/systemd/system/$target.wants/$unit"
  echo "ENABLED $unit -> $target"
done
sudo test -x "$mnt/usr/bin/podman" || { echo "FATAL: podman missing in image" >&2; exit 1; }
sudo test -x "$mnt/usr/sbin/sshd" || { echo "FATAL: sshd missing in image" >&2; exit 1; }
if [ -n "$mod_tar" ]; then
  sudo test -e "$mnt/usr/lib/modules/$(basename "$mod_tar" .tar | sed 's/^modules-//')/kernel/fs/btrfs/btrfs.ko" \
    || { echo "FATAL: btrfs.ko missing after module injection" >&2; exit 1; }
fi
# aib's add_files copies CONTENT ONLY -- its schema has no mode field -- so
# every script the image installs is 0644 unless the manifest's chmod_files
# block names it. A build that dropped or never applied that block yields an
# image whose units die 203/EXEC on the first boot; that is what board 2 was
# written with on 2026-09-02, and it was found by reading the board's disk,
# not the image. Verify it here, before a 12 GiB dd and a reboot, and derive
# the list from the manifest so this file holds no second copy of it.
aib_manifest="$(cd "$(dirname "$0")/../aib" && pwd)/x5h-rootfs.aib.yml"
[ -r "$aib_manifest" ] || { echo "FATAL: manifest unreadable: $aib_manifest" >&2; exit 1; }
execs=$(awk '
  index($0, "  chmod_files:") == 1 { f = 1; next }
  f && (/^[a-zA-Z_]+:/ || /^  [a-zA-Z_]+:/) { f = 0 }
  f && /^[[:space:]]*-[[:space:]]*path:/ { sub(/^[^:]*:[[:space:]]*/, ""); print }
' "$aib_manifest")
[ -n "$execs" ] || { echo "FATAL: no chmod_files paths in $aib_manifest" >&2; exit 1; }
while read -r execpath; do
  sudo test -x "$mnt$execpath" \
    || { echo "FATAL: $execpath is not executable in the image (chmod_files not applied)" >&2; exit 1; }
done <<< "$execs"
echo "EXEC_BITS_VERIFIED $(printf '%s\n' "$execs" | wc -l)"
sudo umount "$mnt"
echo "MAKE_UFS_ROOTFS_OK $out"
