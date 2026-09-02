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

The **role** mechanism described below is newer than that session and is
not yet hardware-verified. Its acceptance markers are `ROLE_SWITCH_PASS`,
`ROLE_FALLBACK_PASS`, `COLDBOOT_PASS` and `BOARD_PARITY_PASS`; until those
are recorded, treat every claim in "Roles" as designed rather than proven.

## Storage layout

The board exposes several UFS logical units. Two of them are 32 GiB and
look alike; the one this layout uses is the one carrying the
`autosd-store` partition label. **Address disks by `/dev/disk/by-path/`
and partitions by partlabel or PARTUUID** — the `/dev/sdX` letters are
assigned in probe order and move between boots, so a device letter that
was right last boot can name a different LUN this boot.

Both boards carry the same two-LUN map. `…5eXX` is shorthand for
`7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5eXX`.

LUN 1, the AutoSD LUN:

| # | partlabel | size | fs | PARTUUID | contents |
|---|---|---|---|---|---|
| 1 | `x5h-boot` | 1 GiB | ext4 | `…5e01` | `Image-autosd`, both dtbs, `x5h-env.txt`, `x5h-role.txt` |
| 2 | `x5h-root` | 12 GiB | ext4 | `…5e02` | AutoSD rootfs, root of the `cr52` and `npu` roles |
| 3 | `autosd-store` | rest | btrfs | `…5e03` | `/var/lib/containers` |

LUN 2:

| # | partlabel | size | fs | PARTUUID | contents |
|---|---|---|---|---|---|
| 1 | `yocto-boot` | 1 GiB | ext4 | `…5e11` | `Image-yocto` and the vendor dtb, for the `yocto` role |
| 2 | `yocto-root` | 8 GiB | ext4 | `…5e12` | vendor Yocto rootfs, root of the `yocto` role |
| 3 | `npu-work` | rest | ext4 | `…5e13` | mounted at `/var/opt/npu`: `cmemdrv.ko`, `ort-rootfs`, artifact sets |

A board with `HAS_YOCTO=0` in its variables file still gets the whole LUN 2
map, with `yocto-boot` and `yocto-root` formatted and left empty. That is
what lets one environment template serve both boards: the `yocto` role is
defined everywhere, and on a board that has no Yocto image its loader
simply fails and the fallback boots `npu` instead.

The PARTUUIDs are fixed constants, not generated, and they are consumed in
four places that must agree with the partition tables: `uboot/x5h-env.tmpl`
(`root=PARTUUID=` for `…5e02` and `…5e12`), `config/var-lib-containers.mount`
(`…5e03`), `scripts/selfboot-smoke.sh` (`…5e02` and `…5e03`) and
`scripts/stage-board.sh` (`…5e11/12/13`). Changing one means changing all of
them. `scripts/x5h-parity.sh` compares the whole partition map across the two
boards as part of its manifest diff.

**Only the LUN 2 table is written by anything in this repository.**
`stage-board.sh partition-lun2` writes `…5e11/12/13` with explicit `sgdisk -u`
flags. **The LUN 1 table, `…5e01/02/03`, is pre-existing on both boards and no
script here creates it**; it was partitioned by hand and it holds the running
AutoSD, so it is verified rather than rewritten. Verify it before converting a
board, because every LUN 1 consumer above fails quietly rather than loudly if
the GUIDs are wrong: `var-lib-containers.mount` is `nofail`, so a mismatched
`…5e03` means the container store silently lands on the root filesystem
instead of on `autosd-store`, and the first symptom is a full root partition
weeks later. The `part.*` keys of the manifest are the check:

```sh
/usr/sbin/x5h-manifest.sh | grep '^part\.0\.'
```

Expect three lines whose values end in `…5e01`, `…5e02` and `…5e03`, in that
order, with labels `x5h-boot`, `x5h-root` and `autosd-store`. (`part.0.*` is
the first LUN in `/dev/disk/by-path` order; `part.1.*` is LUN 2.) Anything
else means the board is not on the pinned map and must be corrected before
`write-root`, not after.

If a LUN 1 partition ever does have to be created by hand, pin its GUID with
`sgdisk -u <n>:<the value from the table above>`. `sgdisk` without `-u`
generates a random one, which is why the one-partition `autosd-store` recipe
in [README.md](README.md) (a Strategy A bring-up step that predates this map)
must not be copied here as it stands.

`/var/lib/containers` is a separate partition because the container store
is the one thing on the board that grows without bound, and keeping it off
the root filesystem means filling it cannot make the system unbootable. It
is mounted `nofail` so a damaged store still yields a usable shell.

**The 2026-08-25 invariant that board 1 carries no NPU boot path is
withdrawn.** Both boards carry all roles, and the NPU payload on board 1 is
vendor NDA material reachable by every root login there. External
developers need the NPU on that board, the owner has accepted the
consequence, and the Tailscale ACL is deliberately unchanged. Anything in
an older document that says board 1 is physically prevented from booting
the NPU is superseded by this paragraph.

## Roles

One image, one environment template, three boot roles. A role is chosen by
a one-line file on `x5h-boot`, and it decides which device tree boots,
which root filesystem is mounted, and which units start.

| Role | Boots | Root | Enables |
|---|---|---|---|
| `cr52` | `Image-autosd` + `r8a78000-ironhide-uio-autosd.dtb` | `…5e02` | CR52 remoteproc, `rpmsg-eth`, the component stack (MRM) |
| `npu` | `Image-autosd` + `r8a78000-ironhide-npu.dtb` | `…5e02` | `var-opt-npu.mount`, `cmemdrv`, `/dev/npuc*` (VisionPilot) |
| `yocto` | `Image-yocto` + the vendor dtb | `…5e12` | the vendor Yocto appliance, on boards with `HAS_YOCTO=1` |

`npu` is the default on both boards. There are three roles rather than one
boot because the shipped memory map does not let the NPU and the realtime
core coexist: the NPU's model-binary region contains the CR52's shared
window and all three of its small RAM regions outright, and under the
vendor NPU device tree a remoteproc `start` panics the kernel by
construction. Reconciling them is a vendor question, not a configuration
one ([npu-bringup.md](npu-bringup.md), "Where this stops").

The split is enforced twice, deliberately. Which `bootcmd_<role>` runs
decides which device tree is loaded, and each role's units carry a
`ConditionKernelCommandLine=x5h.role=<role>` matched against `x5h.role=`
in `bootargs`. Both halves are needed: `systemd.mask=` on the kernel
command line was measured **not** to stop `cr52-remoteproc.service`, so
the unit condition is what actually holds, and the device-tree selection
is what makes the condition's verdict safe.

**A root booted with no `x5h.role=` word at all has no role, and every one
of the nine role-gated units is skipped.** The condition tests for a
specific value; absence does not satisfy any of them. The path that hits
this is the netboot rescue: `uboot/autosd-boot.env` builds
`bootargs_autosd` without an `x5h.role=` word, and the NFS rescue root is
extracted from the same image tar, so `run rescue_autosd` and
`run bootcmd_autosd` both produce a full AutoSD userspace in which nothing
role-gated starts. `/run/x5h/role` then reads `unknown` and
`selfboot-smoke.sh` reports
`SELFBOOT_SMOKE_FAIL reason=unknown_role role=unknown`, which is the
correct verdict and not a defect to chase. The same is true of a board that
has not yet had this environment imported.

That matters here because the netboot rescue is one of the two ways this
document recommends freeing `x5h-root` for `write-root` (see "Staging a
board"). If you need the CR52 chain up on a netbooted root, supply the role
in the rescue bootargs before booting:

```
=> setenv bootargs_autosd "${bootargs_autosd} x5h.role=cr52"
=> run bootcmd_autosd
```

`bootargs_autosd` is double-quoted in `uboot/autosd-boot.env` and has
already expanded, so re-enter the whole line rather than changing one of
its inputs. `uboot/autosd-boot.env` itself is deliberately left alone: it
mirrors environment that is hand-entered on a board's console, and a rescue
boot is the one context where the role should be a conscious choice rather
than a default. [rpmsg-dualboot.md](rpmsg-dualboot.md) carries the same
warning next to the CR52 bring-up procedure it affects.

### The sticky role file and `x5h-role`

`x5h-role.txt` on `x5h-boot` holds one line, `role=<name>`. U-Boot
`env import`s it on every boot, so it survives power cycles, and it is
**sticky**: it stays until something rewrites it. A one-shot variant was
considered and rejected, because silently returning an external developer
to `npu` in the middle of MRM work is the worse failure. The practical
consequence is that a panic, a watchdog reset or an unattended reboot all
come back in the same role the board was left in.

From Linux, `/usr/sbin/x5h-role` reads and writes it:

```
x5h-role                          # current= from /proc/cmdline, next= from x5h-boot
x5h-role set cr52                 # write the next role, stay up
x5h-role set npu --reboot         # write it and reboot into it
```

`set` mounts `x5h-boot` by partlabel, writes a temporary file and `mv`s it
into place, then unmounts, so a failed write changes nothing rather than
leaving a half-written role file. `yocto` is refused with
`ROLE_SET_FAIL reason=yocto_absent` on a board whose `/etc/x5h/board.conf`
does not say `HAS_YOCTO=1`; an unrecognised name is refused with
`ROLE_SET_FAIL reason=bad_role`. Success prints `ROLE_SET next=<role>`.
For off-board testing the tool takes `X5H_BOOT_DIR`, `X5H_BOARD_CONF` and
`X5H_CMDLINE` overrides, which is what `tests/test-x5h-role.sh` drives it
through; on a board, leave all three unset.

The active role is published twice by `x5h-role-banner.service`, from
`x5h.role=` on the command line: `/run/x5h/role` for scripts, and a
`/etc/motd.d` line for whoever logs in. Scripts read `/run/x5h/role`
rather than re-parsing `/proc/cmdline`, so there is one parser.

### Finding the LU, every boot

```
probe_lu=ext4load scsi ${lu}:1 ${loadaddr} x5h-env.txt
find_autosd=setenv lu 2; if run probe_lu; then true; else setenv lu 1; ...
```

`find_autosd` tries LU 2, then 1, then 3, and the probe is an attempt to
read `x5h-env.txt` off partition 1 of that LU. It probes by content because
nothing else on this board is stable: the `/dev/sdX` letters move between
boots, and so do U-Boot's own `scsi` device numbers, which is why the old
hard-coded `scsi 2:1` needed re-checking by eye after any change to the
storage complement. This U-Boot has no `part` command, so listing
partitions across devices and picking programmatically is not available;
probing for a file this repository puts there is the substitute.
`find_yocto` does the same in the other direction, LU 3 then 2 then 1,
probing for `Image-yocto`.

Everything is preceded by `ufs init; scsi rescan` in `bootcmd`. `ufs init`
brings up both UFS controllers and `scsi rescan` enumerates their logical
units; without both, no `scsi` device exists to load from.

### Load addresses, and why `npu` cannot use the stock pair

`cr52` loads at the stock `${kernel_addr_r}` / `${fdt_addr_r}`. Those are
the addresses every CR52 and RPMsg result on this board was taken at, so
they are kept rather than unified for tidiness.

`npu` loads at `0x61080000` / `0x61000000`, the vendor-documented pair. The
stock kernel address sits **inside** `npu_region@8e400000`, so the region's
whole-area contiguous allocation fails with `-EBUSY`. The symptom is one
contiguous-memory device missing while the others appear, and `/proc/iomem`
showing `Kernel code` inside the region; nothing names the load address as
the cause. Note also that U-Boot marks every DRAM bank above the first
`no-map`, so `ext4load` to an address up there fails outright with
`** Reading file would overwrite reserved memory **`.

### The fallback

```
check_role=if test "${role}" = cr52; then true; elif ... else
  echo "x5h: role '${role}' invalid or unreadable, falling back to npu"
  setenv role npu; fi
```

`load_role` clears `role` before trying to import the file, so a failed
read leaves it empty rather than stale, and `check_role` then accepts only
the three known names and otherwise falls back to `npu` with a console
line saying so. A deleted, empty, truncated or garbage role file therefore
boots the default role rather than stopping at the prompt.

`bootcmd_yocto` has a fallback of its own: if `find_yocto` finds no
`Image-yocto` on any LU, it prints a line, sets `role=npu` and runs
`bootcmd_npu`. That is what makes the `yocto` role harmless to define on a
board that has no Yocto image.

### Bootargs every role carries

`bootargs_common` is not adjustable at a session's convenience:

```
pd_ignore_unused clk_ignore_unused rootwait rw panic=10 oops=panic
enforcing=0 ip=<board>::192.168.0.1:255.255.255.0:<hostname>:tsn5:none
```

- `pd_ignore_unused clk_ignore_unused` are mandatory. Omitting them wedges
  the SoC at `clk: Disabling unused clocks` with no oops, no panic, no
  watchdog and no SysRq. Recovery is the SW7 switch.
- `panic=10 oops=panic` is the remote-safety layer: an oops becomes a
  reboot in about ten seconds, back into the same sticky role, instead of
  a board nobody can reach. `selfboot-smoke.sh` asserts
  `panic_on_oops` reads 1 and fails `panic_on_oops_not_set` otherwise.
- `rootwait` matters because UFS probing is not complete when the kernel
  first looks for the root device.
- The full seven-field `ip=` form is required. The bare form falls back to
  DHCP, which nothing on the bench LAN serves.

Per-role additions are only `root=PARTUUID=` and `x5h.role=`. The
`yocto` role's `ip=` names its own hostname (`yocto-x5h-2` on board 2),
which is the one place the two hostnames differ.

### One template, one variables file per board

`uboot/x5h-env.tmpl` is rendered by `uboot/render-env.sh boards/<board>.vars`
into the `x5h-env.txt` that goes on `x5h-boot`. The variables file sets
exactly three keys, and they are the only intended difference between the
two boards:

```
BOARD_IP=192.168.0.20
BOARD_HOSTNAME=autosd-x5h
HAS_YOCTO=0
```

`render-env.sh` refuses a variables file that omits any of them, or whose
`HAS_YOCTO` is not `0` or `1`, rather than rendering a plausible-looking
environment around an empty value. `tests/test-render-env.sh` checks that
the two rendered environments differ **only** in their `ip=` words, that
every role has a `bootcmd_`, and that the load-bearing bootargs survived
rendering.

## Rescue paths

Both netboot commands are preserved and still work; they need the bench
host's TFTP and NFS services.

```
=> run rescue_autosd        # AutoSD on NFS root  (runs bootcmd_autosd)
=> run rescue_yocto_nfs     # BSP Yocto reference boot (runs bootcmd_yocto_nfs)
```

**A rescue boot has no role**, and every role-gated unit is skipped on it;
`selfboot-smoke.sh` there returns
`SELFBOOT_SMOKE_FAIL reason=unknown_role role=unknown`, correctly. See
"Roles" above for why and for the `setenv bootargs_autosd "${bootargs_autosd}
x5h.role=cr52"` line that supplies one when the CR52 chain is needed.

The indirection is not decoration. `bootcmd_yocto` is now the **self-boot**
Yocto role, from `yocto-root` on LU 2, and the board's saved environment
already had a `bootcmd_yocto` meaning the NFS rescue. So the saved one is
renamed **before** the new environment is imported over it, and
`rescue_yocto_nfs` points at the renamed copy:

```
=> setenv bootcmd_yocto_nfs "${bootcmd_yocto}"
```

Do this first, in the same console session, or the import silently
replaces the rescue path with the self-boot one and the rescue is gone
until someone reconstructs it by hand. `stage-board.sh print-uboot` prints
that line as the first of the sequence for exactly this reason.

Catching the U-Boot prompt on a warm reboot needs an Enter roughly every
80 ms: the countdown is about 2.5 s and a slower cadence misses it.

## Staging a board

`scripts/stage-board.sh` is the one staging path, run on the companion. It
reads the board's identity only from `boards/<board>.vars`, so the board is
named by argument and never by an edited copy of the script:

```
scripts/stage-board.sh <x5h1|x5h2> <inputs-dir> <subcommand> [--yes]
```

Run the subcommands in this order. Each ends in exactly one marker:
`<PREFIX>_PASS`, `<PREFIX>_FAIL reason=<slug>`, or `PLAN ONLY: …` for a
gated subcommand invoked without approval. Each is idempotent, with one
exception called out below the table.

| Subcommand | `--yes`? | Does |
|---|---|---|
| `check-inputs` | no | every input present; `Image-autosd` embeds the MP-PHY blob; `rpmsg-eth` is a static aarch64 binary |
| `backup-keys` | no | saves `authorized_keys.d/root` and the ssh host keys off the **live** board |
| `prepare-root` | no | copies `x5h-rootfs.ext4` to the work area and injects hostname, `/etc/x5h/board.conf`, the saved keys, `rpmsg-eth` and the CR52 ELF |
| `write-root` | **yes** | `dd`s the prepared image onto `x5h-root` and verifies it by md5 read-back |
| `partition-lun2` | **yes** | writes the LUN 2 GPT and the three filesystems; destroys what is there |
| `write-boot` | **yes** | replaces the contents of `x5h-boot` with the kernel, both dtbs, `x5h-env.txt` and `x5h-role.txt=npu` |
| `stage-payload` | **yes** | mirrors `<inputs>/npu/` onto `npu-work` with `rsync --delete` |
| `stage-stack` | no | container images and the scenario map, via the existing scripts |
| `print-uboot` | no | prints the console lines that import the environment |

**Every destructive subcommand requires `--yes`, `write-boot` and
`stage-payload` included.** Without it the subcommand prints its plan,
prints `PLAN ONLY: …` and exits 0, having changed nothing. Read the plan;
it is not a formality:

- `partition-lun2` shows `sgdisk -p` of the device it resolved before it
  zaps anything, and it resolves the LUN 2 glob to exactly one device
  first, refusing an ambiguous or absent match.
- `stage-payload` runs `rsync --dry-run --itemize-changes` and reports how
  many paths **would be deleted** from the board and how many sent, listing
  up to fifty of the deletions by name. `--delete` mirrors, so anything
  under `/var/opt/npu` on the board that is absent from `<inputs>/npu/` is
  removed, and that directory holds vendor material and calibration
  artifacts that exist in exactly one place. Confirm the inputs directory
  is the full set and not a narrowed copy before approving.
- `write-boot` extracts over the partition first, verifies every file's
  md5 against the staged copy, and only then deletes the other regular
  files on `x5h-boot`, so the partition is never empty at any instant.

**`partition-lun2` is the one subcommand that is not idempotent.** It is
idempotent in *shape*: the same three partitions, the same labels, the same
pinned PARTUUIDs, whatever it finds. It is not idempotent in *content*, and
that difference is the whole of it: it runs `mkfs.ext4` over all three, so a
second run erases `yocto-boot`, `yocto-root` and everything on `npu-work`.
On board 2 that means the vendor Yocto appliance and the staged NPU payload
together. `stage-payload` puts the NPU payload back from `<inputs>/npu/`;
**nothing in this repository puts Yocto back, and no document here carries a
recipe for it**: the Yocto image has to be reinstalled by the vendor procedure
afterwards. Treat `partition-lun2` as a one-time conversion step
per board, not as part of a re-stage.

**The board must not be running from `x5h-root` during `write-root`.** The
subcommand checks: it resolves both the mounted root's source and the
`x5h-root` partlabel and refuses with
`STAGE_WRITE_FAIL reason=board_running_from_target` if they are the same
device. Boot the board into the `yocto` role, or netboot it through
`rescue_autosd`, before running it. It also asserts that the partlabel
resolves to a real block device first, because `dd` to a dangling symlink
path would quietly create a regular file there and read back the file it
had just written: a pass that wrote nothing to the disk.

**The keys are carried forward, not recreated.** `backup-keys` must run
before `prepare-root`, which refuses with
`STAGE_ROOT_FAIL reason=run_backup_keys_first` otherwise. It pulls
`/etc/ssh/authorized_keys.d/root` and `/etc/ssh/ssh_host_*` off the live
board and `prepare-root` restores them into the new image, so external
developers keep their access and see no host-key change across a re-image.
That is also why the order matters in the other direction: once
`write-root` has run, the keys that were on the board are gone.

Then deliver the environment over the serial console. The values contain
semicolons, and if you are driving U-Boot through `tmux`, **semicolons do
not survive `send-keys`**: they are consumed as tmux's own command
separator. So the environment is delivered as a file and imported, never
typed. `stage-board.sh <board> <inputs> print-uboot` prints the exact
sequence:

```
=> setenv bootcmd_yocto_nfs "${bootcmd_yocto}"
=> ufs init
=> scsi rescan
=> ext4load scsi 2:1 ${loadaddr} x5h-role.txt
=> ext4load scsi 2:1 ${loadaddr} x5h-env.txt
=> env import -t ${loadaddr} ${filesize}
=> saveenv
=> printenv bootcmd role
=> boot
```

If the first `ext4load` fails, try `scsi 1:1` and use that LU for the rest
of the sequence. Only this one-off delivery needs a hard-coded LU number;
from the saved environment onwards, `find_autosd` probes for it.

The saved environment lives in eMMC, not on UFS, so it survives every UFS
flash. That cuts both ways: re-imaging a board does **not** clear a stale
environment, and device letters in anything you saved by hand will have
moved.

### Building the inputs

The rootfs written to `x5h-root` is the **same tar the CI pipeline builds
and the QEMU gate validates**, reassembled into a filesystem image:

```
scripts/make-ufs-rootfs.sh x5h-rootfs.tar x5h-rootfs.ext4 [size]
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

`make-ufs-rootfs.sh` also creates the `.wants` symlinks that
`80-x5h.preset` describes, because osbuild never runs `systemctl preset`
and nothing in the image links those units into their targets otherwise.
It fails loudly if the preset names a unit the image does not carry, so
the preset stays the single place that says what is enabled. This used to
be a hand step for `sshd.service` alone, and it is now the mechanism for
every unit the preset lists.

The sshd drop-in is key-only, and `config/x5h-authorized-keys` ships with no
key in it, so a freshly built image has no way in over the network. Put your
own public key there before building; `stage-board.sh` then carries the live
board's own `authorized_keys` forward on top of that. The root password
remains a serial-console credential either way.

#### Why a script instead of a CI artifact

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

#### The boot partition

**Use the board kernel, not the CI kernel.** The kernel is built twice from
one source: the CI/QEMU-gate image with `CONFIG_EXTRA_FIRMWARE=""`, and the
board image that additionally embeds the MP-PHY firmware blob. That blob
comes from the vendor SDK, so CI cannot produce the board image — *both*
artifacts a CI run publishes are the gate variant.

Booting the gate kernel on the board leaves the TSN interface entirely
absent: no `tsn5`, no network, no SSH. The symptom looks like a
configuration problem and is not. `stage-board.sh check-inputs` refuses a
firmware-less `Image-autosd` outright, by extracting the embedded config
and looking for the `CONFIG_EXTRA_FIRMWARE` line, so the mistake cannot
reach `x5h-boot` through the staging path.

Take `Image-autosd` from the locally built board kernel (the one the TFTP
netboot serves, built with `--firmware`). The dtb is identical in both. The
two builds share source SHA, toolchain and fragments — the only permitted
config delta is the `CONFIG_EXTRA_FIRMWARE` pair — so the modules from a CI
run pair correctly with the board kernel.

### First boot

Format the container store once, on a board whose `autosd-store` partition
is new:

```
mkfs.btrfs -f -L autosd-store /dev/disk/by-partlabel/autosd-store
```

**It is mounted by an explicit unit, not by `/etc/fstab`.** On this image
systemd's fstab generator does not run at boot — `/run/systemd/generator/`
comes up with no mount units, even though invoking
`/usr/lib/systemd/system-generators/systemd-fstab-generator` by hand
parses the very same `/etc/fstab` and emits a correct unit. A `nofail`
entry therefore fails *silently*: no mount, no error, and podman quietly
uses the root filesystem instead.

`var-lib-containers.mount` (the filename must match the mount point) ships
in the image and is enabled by `80-x5h.preset`, so this is no longer
something to write by hand; `config/var-lib-containers.mount` is the
source. The same reasoning produced `var-opt-npu.mount` for the `npu`
role's `npu-work` partition, whose name is `var-opt-npu` and not `opt-npu`
because `/opt` on this rootfs is a symlink to `var/opt`.

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

This is also why `automotive-image-builder` refuses `/usr/local` outright
and everything the image ships lives under `/usr/sbin` instead, and why
`stage-board.sh prepare-root` writes the `rpmsg-eth` binary to
`<mnt>/var/usrlocal/bin/rpmsg-eth` rather than through the symlink.

## Verifying a self-boot

```
sh /usr/sbin/selfboot-smoke.sh
```

Expect `SELFBOOT_SMOKE_PASS root=… partuuid=… role=…`. The script resolves
the mounted root back to its PARTUUID rather than trusting `/dev/sdX`,
rejects an NFS root outright, checks the pieces baked into the image,
confirms `sshd` is running and `podman` works, asserts that the role's own
bring-up unit is active (`cr52-remoteproc.service` in the `cr52` role,
`x5h-npu.service` in the `npu` role) and that `panic_on_oops` reads 1.
Anything else prints `SELFBOOT_SMOKE_FAIL reason=<what>`.

It is deliberately **not** a link test any more. It used to finish by
running `rpmsg-smoke.sh`, whose remoteproc restart races
`rpmsg-eth.service` and oopsed `rpmsg_char`, leaving RPMsg dead until the
next SoC reset; under `oops=panic` that is now a reboot. The per-role link
checks are separate scripts:

```
/usr/sbin/rpmsg-eth-smoke.sh              # cr52 role: RPMSG_ETH_PING_PASS
/usr/sbin/npu-contract-smoke.sh <artifacts>   # npu role:  NPU_CONTRACT_PASS
```

All three of these ship in the image (`aib/x5h-rootfs.aib.yml` installs them
under `/usr/sbin`), so a board that has just been written by `stage-board.sh
write-root` already has them and there is nothing to copy across. Run them by
absolute path: `/usr/sbin` is on root's `PATH` on this image, but naming the
path is what makes it obvious in a session log which copy was graded.

A board flashed from an image built **before** these entries existed will not
have `selfboot-smoke.sh` or `rpmsg-eth-smoke.sh`, only `x5h-manifest.sh`,
`npu-contract-smoke.sh` and `x5h-stack-smoke.sh`. Check with
`command -v selfboot-smoke.sh` rather than reading a `command not found` as a
broken image; the fix is a rebuilt image and a `write-root`, not a hand copy
into `/var/tmp`, which is what goes stale against the contract it grades.

Run the smoke over SSH rather than the serial console when you want to
prove the remote path works too.

`/usr/sbin/x5h-manifest.sh` prints the board's normalized configuration
manifest on stdout and one marker on stderr (`X5H_MANIFEST_OK`, or
`X5H_MANIFEST_FAIL reason=<slug>` with nothing on stdout at all). Grade it
by that marker, not by its exit code, and never by "the file looks
plausible": a manifest that lost a whole category is byte-for-byte
indistinguishable from a complete one. `scripts/x5h-parity.sh` diffs two
boards' manifests, subtracts the keys that legitimately derive from the
variables files, refuses an incomplete manifest or the same manifest handed
in twice, and prints `BOARD_PARITY_PASS` on an empty remainder.

## Reset behaviour, and what restarts the realtime core

A plain `reboot` from Linux is a **full SoC reset**, not just an APU
restart. Linux issues PSCI `SYSTEM_RESET`, and the firmware implements it
as a cold reset — the realtime console prints

```
SM: I [system_notification:101] PSCI (BL31) has transited to graceful coldreset with timeout 0 ms
```

and the CR52 restarts and re-loads its flashed payload. Observed on every
warm reboot from both Yocto and AutoSD.

This matters in three directions:

- **It is the remote reset mechanism.** Restarting the realtime core needs
  no switch, no power cycle and no serial access — `ssh root@<board>
  reboot` is enough, and because `bootcmd` now self-boots, the board comes
  back on its own with a fresh realtime payload. See
  [cr52-slot-update.md](cr52-slot-update.md).
- **A warm reboot is not a way to keep the realtime core running.** If you
  need the CR52 to survive, do not reboot Linux.
- **It is what makes a role switch safe.** In the `npu` role the CR52's
  memory lies inside the NPU's regions and must be assumed overwritten;
  `x5h-role set cr52 --reboot` reloads it from its flashed slot on the way
  back. Nothing has to be repaired by hand, and equally nothing short of
  that reset repairs it.

Earlier notes in this repo claimed a soft reboot does not reset the
realtime core and that a physical switch was required. That is wrong and
has been retired; it was measured four times across both operating
systems, plus the reset used in each slot-update cycle.

## Related

- [CR52 dual boot + RPMsg](rpmsg-dualboot.md): the realtime payload and
  the RPMsg link the `cr52` role brings up.
- [NPU bring-up](npu-bringup.md): what the `npu` role exists for, and the
  container contract it presents.
- [Component stack](component-stack.md): the MRM demo, `cr52` role only.
- [CR52 slot update](cr52-slot-update.md): updating the realtime
  firmware from Linux, which self-boot makes remotely reachable.
- [Companion host](companion-host.md): the bench gateway `stage-board.sh`
  runs on, and the two-board bench layout.
