# X5H UFS self-boot: unattended AutoSD from onboard storage

Boots AutoSD on the X5H from the board's own UFS storage, with no TFTP
server and no NFS root in the path. Power the board on and it reaches a
login prompt by itself.

Until this, the board netbooted: U-Boot pulled the kernel over TFTP and the
kernel mounted its root over NFS from a specific host on the bench LAN. That
makes the board unusable without that host, and unusable remotely. Self-boot
removes both dependencies; the netboot paths are kept as named rescue
commands rather than deleted.

## Status on real hardware

Validated on the board on 2026-08-07 on the rebuilt `6.1.102-autosd`
kernel. Root is the UFS partition, with no NFS mount anywhere, and the
board reaches its login prompt unattended:

```
findmnt -n -o SOURCE,FSTYPE /   → /dev/sdc2 ext4
blkid -s PARTUUID …             → 7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e02
mount | grep -c nfs             → 0
nproc                           → 32
```

## Storage layout

The board exposes several UFS logical units. Two of them are 32 GiB and
look alike; the one this layout uses is the one carrying the
`autosd-store` partition label. **Address disks by `/dev/disk/by-path/`
and partitions by partlabel or PARTUUID** — the `/dev/sdX` letters are
assigned in probe order and move between boots, so a device letter that
was right last boot can name a different LUN this boot.

The data LUN is partitioned as:

| # | partlabel | size | fs | PARTUUID | contents |
|---|---|---|---|---|---|
| 1 | `x5h-boot` | 1 GiB | ext4 | `7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e01` | `Image-autosd`, dtb, `selfboot-env.txt` |
| 2 | `x5h-root` | 12 GiB | ext4 | `7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e02` | AutoSD rootfs |
| 3 | `autosd-store` | rest | btrfs | `7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e03` | `/var/lib/containers` |

The PARTUUIDs are fixed constants, not generated. They appear in three
places that must agree: the partition table, `bootargs_autosd_ufs`, and
`selfboot-smoke.sh`. Changing one means changing all three.

`/var/lib/containers` is a separate partition because the container store
is the one thing on the board that grows without bound, and keeping it off
the root filesystem means filling it cannot make the system unbootable. It
is mounted `nofail` so a damaged store still yields a usable shell.

## Boot flow

`bootcmd` runs `bootcmd_autosd_ufs`, which is:

```
ufs init; scsi rescan;
ext4load scsi 2:1 ${kernel_addr_r} Image-autosd;
ext4load scsi 2:1 ${fdt_addr_r} r8a78000-ironhide-uio-autosd.dtb;
setenv bootargs ${bootargs_autosd_ufs};
booti ${kernel_addr_r} - ${fdt_addr_r}
```

`ufs init` brings up both UFS controllers and `scsi rescan` enumerates
their logical units; without both, no `scsi` device exists to load from.

The kernel finds its root by PARTUUID, so `bootargs` never names a
`/dev/sdX`:

```
root=PARTUUID=7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e02 rootwait rw
```

`rootwait` matters: UFS probing is not complete when the kernel first
looks for the root device.

### About that `scsi 2:1`

This U-Boot has **no `part` command**, so there is no way to list
partitions across devices and pick the right one programmatically. The
index is confirmed by looking at the contents instead:

```
=> ext4ls scsi 2:1 /
```

The correct device lists `Image-autosd` and the dtb. On this board the
neighbouring index is a different 32 GiB LUN holding unrelated data, and
it is immediately obvious which is which from the file listing. Re-check
this after any change to the storage complement rather than trusting the
number.

## Installing or reinstalling the environment

The multi-command values contain semicolons. If you are driving U-Boot
over a serial console through `tmux`, **semicolons do not survive
`send-keys`** — they are consumed as tmux's own command separator. So the
environment is delivered as a file and imported, never typed:

```
=> ufs init
=> scsi rescan
=> ext4load scsi 2:1 ${loadaddr} selfboot-env.txt
=> env import -t ${loadaddr} ${filesize}
=> saveenv
```

`selfboot-env.txt` (in `uboot/`) is kept on the boot partition rather than
served over TFTP, so restoring the boot environment needs no host at all —
which is the point of a self-booting board. Copy it to p1 whenever you
update it:

```
mount /dev/disk/by-partlabel/x5h-boot /mnt
cp selfboot-env.txt /mnt/ && umount /mnt
```

## Rescue paths

Both netboot commands are preserved and still work; they need the bench
host's TFTP and NFS services.

```
=> run bootcmd_yocto     # BSP Yocto reference boot (the original default)
=> run bootcmd_autosd    # AutoSD on NFS root
```

To make netboot the default again:

```
=> setenv bootcmd run bootcmd_yocto
=> saveenv
```

and to return to self-boot:

```
=> setenv bootcmd run bootcmd_autosd_ufs
=> saveenv
```

Catching the U-Boot prompt on a warm reboot needs an Enter roughly every
80 ms — the countdown is about 2.5 s and a slower cadence misses it.

## Populating the partitions

The rootfs written to p2 is the **same tar the CI pipeline builds and the
QEMU gate validates**, reassembled into a filesystem image:

```
scripts/make-ufs-rootfs.sh x5h-rootfs.tar x5h-rootfs.ext4 [size]
dd if=x5h-rootfs.ext4 of=/dev/disk/by-partlabel/x5h-root bs=4M conv=fsync
```

The reassembly must preserve extended attributes — file capabilities and
SELinux labels live there, and a plain `tar xf` silently drops them,
producing an image that boots but misbehaves. `make-ufs-rootfs.sh` uses
the same xattr-preserving recipe as the gate. Verify a built image without
mounting it:

```
debugfs -R "ea_list /usr/bin/newgidmap" x5h-rootfs.ext4
# expect security.selinux and security.capability
```

**The rootfs tar contains no kernel modules.** The rebuilt kernel's modules
are a separate `modules-<release>.tar` in the same CI bundle, and they have
to be unpacked into the image too — `make-ufs-rootfs.sh` picks up the one
sitting beside the rootfs tar automatically.

An image without them still boots, because ext4 and the essential drivers
are built in, so the mistake is silent. What breaks is everything modular:
`btrfs` (the container store will not mount, even though `mkfs.btrfs`
succeeded — mkfs is userspace and the mount is not), `overlay` (podman
storage), and `rpmsg_client_sample` (the CR52 smoke). If a freshly written
board is missing modules, note that the image cannot be patched in place:
this rootfs ships no `tar`, only `cpio` and `gzip`. Rebuild the image
instead.

### Why a script instead of a CI artifact

The spec listed a raw image as a CI deliverable; it is derived on the host
instead. The recipe is byte-for-byte the one CI already runs for the gate,
so the result is the same bytes CI validated, and publishing a multi-GiB
mostly-empty filesystem image from CI would only re-encode the tar that is
already the artifact.

Note the image is smaller than the partition, so grow the filesystem after
writing it:

```
resize2fs /dev/disk/by-partlabel/x5h-root
```

`e2fsprogs` is installed in the image for exactly this reason — it is not
in the AutoSD base package set.

### The boot partition

**Use the board kernel, not the CI kernel.** The kernel is built twice from
one source: the CI/QEMU-gate image with `CONFIG_EXTRA_FIRMWARE=""`, and the
board image that additionally embeds the MP-PHY firmware blob. That blob
comes from the vendor SDK, so CI cannot produce the board image — *both*
artifacts a CI run publishes are the gate variant.

Booting the gate kernel on the board leaves the TSN interface entirely
absent: no `tsn5`, no network, no SSH. The symptom looks like a
configuration problem and is not.

Take `Image-autosd` from the locally built board kernel (the one the TFTP
netboot serves, built with `--firmware`). The dtb is identical in both. The
two builds share source SHA, toolchain and fragments — the only permitted
config delta is the `CONFIG_EXTRA_FIRMWARE` pair — so the modules from a CI
run pair correctly with the board kernel.

The boot partition can be built without root using `mkfs.ext4 -d`, which
populates an image from a directory with no loop mount:

```
mkfs.ext4 -q -F -L x5h-boot -d <dir-with-kernel-dtb-env> x5h-boot.ext4
```

### First boot

Format the container store once:

```
mkfs.btrfs -f -L autosd-store /dev/disk/by-partlabel/autosd-store
```

**Mount it with an explicit unit, not `/etc/fstab`.** On this image
systemd's fstab generator does not run at boot — `/run/systemd/generator/`
comes up with no mount units, even though invoking
`/usr/lib/systemd/system-generators/systemd-fstab-generator` by hand
parses the very same `/etc/fstab` and emits a correct unit. A `nofail`
entry therefore fails *silently*: no mount, no error, and podman quietly
uses the root filesystem instead.

Write `/etc/systemd/system/var-lib-containers.mount` (the filename must
match the mount point) and enable it:

```
[Unit]
Description=X5H container store (UFS partition autosd-store)
After=local-fs-pre.target
DefaultDependencies=no

[Mount]
What=/dev/disk/by-partuuid/7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e03
Where=/var/lib/containers
Type=btrfs
Options=defaults,nofail

[Install]
WantedBy=local-fs.target
```

```
systemctl daemon-reload && systemctl enable --now var-lib-containers.mount
```

### Enabling sshd

The `enable sshd.service` preset in the image is **not** applied at build
time — osbuild never runs `systemctl preset`, so nothing links the unit
into `multi-user.target`. Create the symlink explicitly when staging the
image, or sshd will not start and the board will have no remote access:

```
ln -sf /usr/lib/systemd/system/sshd.service \
       <mnt>/etc/systemd/system/multi-user.target.wants/sshd.service
```

The sshd drop-in is key-only, and `config/x5h-authorized-keys` ships with no
key in it, so a freshly built image has no way in over the network. Put your
own public key there before building, or append it to
`<mnt>/etc/ssh/authorized_keys.d/root` while staging; the root password
remains a serial-console credential either way.

### A podman gotcha after adding modules

containers/storage caches the result of its overlay-support probe. If
podman ever ran while `overlay.ko` was missing, it keeps reporting
`kernel does not support overlay fs` even after the module is installed
and loaded — the debug log gives it away with "Cached value indicated that
overlay is not supported". The cache lives in the tmpfs runroot, so a
reboot clears it.

`btrfs-progs` is in the image but **not** in the BSP Yocto rootfs, so do
this from AutoSD. Conversely `mkfs.ext4` and `resize2fs` are in the Yocto
rootfs and were missing from AutoSD before `e2fsprogs` was added. The two
systems have complementary tooling; check before assuming a tool is there.

### A trap when staging files into the image

The rootfs is ostree-structured and ships `/usr/local` as a symlink to
`../var/usrlocal`, while `/var` in a freshly written image is empty. So
installing into `<mnt>/usr/local/bin/` fails until the target exists:

```
mkdir -p <mnt>/var/usrlocal/bin <mnt>/var/lib/containers
```

## Verifying a self-boot

```
sh /usr/local/bin/selfboot-smoke.sh
```

Expect `SELFBOOT_SMOKE_PASS root=… partuuid=…`. The script resolves the
mounted root back to its PARTUUID rather than trusting `/dev/sdX`, rejects
an NFS root outright, checks the pieces baked into the image, confirms
`sshd` is running and `podman` works, and finishes with the CR52 RPMsg
round trip. Anything else prints `SELFBOOT_SMOKE_FAIL reason=<what>`.

Run it over SSH rather than the serial console when you want to prove the
remote path works too.

## Reset behaviour, and what restarts the realtime core

A plain `reboot` from Linux is a **full SoC reset**, not just an APU
restart. Linux issues PSCI `SYSTEM_RESET`, and the firmware implements it
as a cold reset — the realtime console prints

```
SM: I [system_notification:101] PSCI (BL31) has transited to graceful coldreset with timeout 0 ms
```

and the CR52 restarts and re-loads its flashed payload. Observed on every
warm reboot from both Yocto and AutoSD.

This matters in two directions:

- **It is the remote reset mechanism.** Restarting the realtime core needs
  no switch, no power cycle and no serial access — `ssh root@<board>
  reboot` is enough, and because `bootcmd` now self-boots, the board comes
  back on its own with a fresh realtime payload. See
  [cr52-slot-update.md](cr52-slot-update.md).
- **A warm reboot is not a way to keep the realtime core running.** If you
  need the CR52 to survive, do not reboot Linux.

Earlier notes in this repo claimed a soft reboot does not reset the
realtime core and that a physical switch was required. That is wrong and
has been retired; it was measured four times across both operating
systems, plus the reset used in each slot-update cycle.

## Related

- [CR52 dual boot + RPMsg](rpmsg-dualboot.md) — the realtime payload and
  the RPMsg round trip the smoke script exercises.
- [CR52 slot update](cr52-slot-update.md) — updating the realtime
  firmware from Linux, which self-boot makes remotely reachable.
