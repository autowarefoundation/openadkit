#!/bin/sh
# selfboot-smoke.sh — board-side proof the UFS self-boot is the real thing.
#
# Run this after the board has come up on its own (no host TFTP/NFS in the
# path) to confirm that what booted is the UFS rootfs, that the pieces baked
# into the image are present and active, and that the boot reached its role.
# Markers: SELFBOOT_SMOKE_PASS / SELFBOOT_SMOKE_FAIL reason=<...>
#
# ROLE-AWARE, AND NO LONGER A CR52 TEST. This script used to finish by running
# rpmsg-smoke.sh, which restarts remoteproc and races rpmsg-eth.service: the
# restart oopsed rpmsg_char and left RPMsg dead until the next SoC reset. Under
# the `oops=panic panic=10` bootargs every role now carries, that oops is a
# reboot instead, so the line is gone. The per-role link check is
# rpmsg-eth-smoke.sh (cr52 role) and npu-contract-smoke.sh (npu role); this
# script only asserts that the role's own bring-up unit reached active.
set -u

ROOT_PARTUUID=7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e02
STORE_PARTUUID=7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e03

fail() { echo "SELFBOOT_SMOKE_FAIL reason=$1"; exit 1; }

# --- root identity -----------------------------------------------------
# UFS device letters move between boots, so /dev/sdX says nothing about
# which partition we are on. Resolve the mounted root back to its PARTUUID
# and compare against the one the bootargs asked for; that is the only
# check that actually proves we booted the intended partition.
rootsrc=$(findmnt -n -o SOURCE /) || fail nofindmnt
case "$rootsrc" in
  *nfs*|*:/*) fail "root_is_nfs src=$rootsrc" ;;
esac
rootuuid=$(blkid -s PARTUUID -o value "$rootsrc" 2>/dev/null)
[ "$rootuuid" = "$ROOT_PARTUUID" ] || fail "root_partuuid=${rootuuid:-unknown} src=$rootsrc"

# --- content baked by the aib manifest ---------------------------------
command -v mkfs.ext4 >/dev/null || fail e2fsprogs_missing
test -f /etc/ssh/sshd_config.d/50-x5h.conf || fail sshd_dropin_missing
test -f /etc/ssh/authorized_keys.d/root || fail authorized_keys_missing
test -f /etc/modprobe.d/x5h-rpmsg-diag.conf || fail rpmsg_blacklist_missing
systemctl is-active sshd >/dev/null 2>&1 || fail sshd_inactive

# --- container runtime + its store -------------------------------------
podman info >/dev/null 2>&1 || fail podman
if mountpoint -q /var/lib/containers; then
  storeuuid=$(blkid -s PARTUUID -o value "$(findmnt -n -o SOURCE /var/lib/containers)" 2>/dev/null)
  [ "$storeuuid" = "$STORE_PARTUUID" ] || echo "SELFBOOT_NOTE containers-store partuuid=$storeuuid (expected $STORE_PARTUUID)"
else
  echo "SELFBOOT_NOTE containers-store not mounted"
fi

# --- the boot role, and the unit that role brings up --------------------
# /run/x5h/role is written by x5h-role-banner.service from x5h.role= on the
# kernel command line, so an empty or missing file is itself a finding: the
# banner unit did not run, and nothing downstream that keys on the role can be
# trusted either.
role=$(cat /run/x5h/role 2>/dev/null || echo unknown)
case "$role" in
  cr52) systemctl is-active --quiet cr52-remoteproc.service || fail cr52_remoteproc_inactive ;;
  npu)  systemctl is-active --quiet x5h-npu.service || fail npu_not_ready ;;
  *) fail "unknown_role role=$role" ;;
esac

# panic_on_oops is the load-bearing remote-safety layer: it is what turns an
# oops on an unattended board into a reboot back into the same sticky role
# rather than a wedge nobody can reach.
[ "$(cat /proc/sys/kernel/panic_on_oops)" = 1 ] || fail panic_on_oops_not_set

echo "SELFBOOT_SMOKE_PASS root=$rootsrc partuuid=$rootuuid role=$role"
