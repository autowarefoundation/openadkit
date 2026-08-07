#!/usr/bin/env bash
# Boot the x5h rootfs export under the BSP-constraint-mimic kernel.
# Usage: run-qemu-gate.sh <Image> <rootfs.ext4> <blank-disk> [extra qemu args...]
# TCG with -cpu cortex-a76 (never -cpu max: aborts under TCG). KVM only if the
# host is aarch64 with a writable /dev/kvm — the Ubicloud arm64 runner has none.
set -euo pipefail
if [ "$#" -lt 3 ]; then
  echo "Usage: $0 <Image> <rootfs.ext4> <blank-disk> [extra qemu args...]" >&2
  exit 1
fi
KERNEL="$1"; ROOTFS="$2"; BLANK="$3"; shift 3 || true
[ -f "$BLANK" ] || qemu-img create -f raw "$BLANK" 8G
if [ "$(uname -m)" = "aarch64" ] && [ -w /dev/kvm ]; then
  ACCEL=(-accel kvm -cpu host)
else
  ACCEL=(-accel tcg -cpu cortex-a76)
fi
exec qemu-system-aarch64 \
  -machine virt -smp 8 -m 4G "${ACCEL[@]}" \
  -kernel "$KERNEL" \
  -append "root=/dev/vda rw console=ttyAMA0 selinux=0 systemd.show_status=1" \
  -drive "file=$ROOTFS,if=virtio,format=raw,index=0" \
  -drive "file=$BLANK,if=virtio,format=raw,index=1" \
  -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
  -nographic "$@"
