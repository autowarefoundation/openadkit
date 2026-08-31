# X5H UIO: reaching the SoC's accelerator blocks from userspace

The X5H describes a large set of accelerator and capture blocks — image
processing, ISP, video capture, CSI receivers, the DSP subsystem, the RPMsg
shared-memory and IPI windows — as `generic-uio` device-tree nodes. Nothing
in the kernel drives them; they are handed to userspace through
`uio_pdrv_genirq`, which maps each node's register window and delivers its
interrupt to whatever opens `/dev/uioN`.

This is how the Renesas ONNX Runtime execution provider is expected to reach
the NPU, so it is a prerequisite for that work rather than an unrelated
platform detail. It is not sufficient on its own — see
[What this does not cover](#what-this-does-not-cover).

## The trap: loaded, but bound to nothing

`uio_pdrv_genirq` ships wildcard OF aliases (`of:N*T*C*`), so udev autoloads
it during boot on the first unmatched device-tree node. But the module's
`of_match_table` starts empty and is filled from the `of_id` module
parameter, so a load with no parameter binds nothing at all.

The failure is silent and reads as a device-tree problem. `lsmod` shows the
module present, the device-tree nodes are there and carry no `status`
property (so they are enabled), and yet `/dev/uio*` does not exist,
`/sys/class/uio` is empty, and `dmesg` prints nothing — there is no probe to
fail. Every symptom points at the dtb, and the dtb is fine.

`config/x5h-uio.conf` supplies the parameter:

```
options uio_pdrv_genirq of_id=generic-uio
```

A `modprobe.d` drop-in is the right place for it precisely because the
module is modprobe-loaded. The alternative — `uio_pdrv_genirq.of_id=` on the
kernel command line — would mean editing `bootargs_autosd_ufs`, which is
coupled to the self-boot PARTUUIDs in three places that must agree (see
[selfboot.md](selfboot.md)); this needs none of that.

## Verified on hardware, 2026-08-10

On the self-booted `6.1.102-autosd` board:

| measure | value |
|---|---|
| `generic-uio` nodes in the live device tree | 201 |
| UIO devices bound | 177 (`/dev/uio0` … `/dev/uio176`) |
| probe errors in `dmesg` | none |

The devices come up named from each node's `linux,uio-name`, which is what
makes them addressable by something other than a probe-order index. The name
lands in `/sys/class/uio/uioN/name`; the device node itself is still
`/dev/uioN`, and still `0600 root:root`. Turning the name into a path takes a
udev rule — see [From a sysfs name to a `/dev`
path](#from-a-sysfs-name-to-a-dev-path).

| name prefix | count | block |
|---|---|---|
| `vin_*` | 80 | video capture |
| `rsip_e_*` | 20 | RSIP engine |
| `rfso_*` | 20 | RFSO |
| `ims_*` | 8 | IMR-LX7 scaler |
| `ostm_*` | 6 | OS timer |
| `vspx_*`, `vcp5_*`, `tisp_*`, `imr_*`, `fcpvx_*`, `fcpc_*`, `csi_*`, `cisp_*` | 4 each | VSPX / DSP subsystem / ISP / CSI |
| `rpmsg_shm0`, `rpmsg_ipi0` | 1 each | CR52 shared memory and IPI |

Mappings resolve to the addresses the device tree declares — `rpmsg_shm0`
becomes `uio0`, and its `map0` base and size match the `cr52_ram0`
reserved-memory region exactly. Read the values from the booted device tree
rather than from here; see the note on where numbers live in
[npu-bringup.md](npu-bringup.md).

**Sibling nodes that share a register window do bind.** Several blocks are
described as one node for the window plus additional nodes carrying the same
`reg` and a different interrupt each; the `irq_vcp5_*` nodes come up at the
same base as `vcp5_0`. This pattern was in doubt and is now settled, which
matters because the NPU is described the same way.

24 of the 201 nodes did not bind, with nothing logged. Not investigated —
none of them are in a subsystem this branch depends on.

### Checking it

```sh
ls -d /sys/class/uio/uio* | wc -l
for d in /sys/class/uio/uio*; do echo "$(basename "$d") $(cat "$d/name")"; done
```

An empty result on a board whose device tree has `generic-uio` nodes means
the drop-in did not reach the image, or the module was loaded before it was
read. `modprobe -r uio_pdrv_genirq && modprobe uio_pdrv_genirq` re-reads it
without a reboot; the module binds nothing beforehand, so unloading it is a
no-op.

## From a sysfs name to a `/dev` path

Binding the devices and naming them is not the same as making them openable.
UIO creates `/dev/uioN` numbered by probe order and `0600 root:root`; the
`linux,uio-name` reaches `/sys/class/uio/uioN/name` and stops there. A runtime
that opens `/dev/npuc0` therefore gets `ENOENT` on a board where the device
tree, the module binding and the sysfs name are all correct — the same shape of
failure as the `of_id` trap above, and misleading in the same direction.

`config/51-x5h-uio.rules` closes it, and `config/52-x5h-cmem.rules` does the
same for the contiguous-memory devices:

```
SUBSYSTEM=="uio", SYMLINK+="$attr{name}"
SUBSYSTEM=="uio", ATTR{name}=="npuc*", MODE="0666"
```

One symlink rule covers all 177 devices at once. The mode line is deliberately
narrower than the vendor's reference rootfs, which relaxes every UIO device on
the board: only the NPU cluster is opened to a non-root process. Widen that
match if the runtime turns out to need another block — a blanket `0666` here
would hand every capture, ISP and RSIP block on the SoC to any local process.

**Verified on hardware, 2026-08-11.** All 177 devices gained a name symlink
(`/dev/rpmsg_shm0` → `uio0`, `/dev/rpmsg_ipi0` → `uio1`); nodes outside the
`npuc*` match stayed `0600`. The `ATTR{name}` branch was exercised separately
against `rpmsg_shm*` — `/dev/uio0` became `0666` and `/dev/uio1` did not — since
no `npuc*` device exists until the NPU nodes are in the device tree. With the
cmem rule in place, a fresh `cmemdrv` load produced `/dev/cmem0` at `0666`
directly.

**Removing a rule does not undo it.** udev applies modes when it processes a
device; a `udevadm trigger` after deleting the rule leaves the node at whatever
it was last set to. The mode returns only when the node is re-created — a
reboot, or unbinding and rebinding the driver. Testing from
`/run/udev/rules.d` keeps the *rule* out of the image, but the permission
change it made outlives it, so put the node back by hand.

## What this does not cover

Enabling UIO does not by itself make the NPU reachable. Three things are still
missing, and none of them is fixed by this drop-in:

- **The NPU's device-tree nodes are absent from the board's dtb.** The board
  boots `r8a78000-ironhide-uio-autosd.dtb`, built from the public
  `renesas-rcar/linux-bsp` tree pinned by `kernel/build-bsp-kernel.sh`. That
  tree's UIO dtsi describes the ISP, IMR, VSPX, DSP, capture and RSIP blocks
  but has no NPU node — only the NPU's SMMUs, disabled. The vendor SDK's own
  UIO device-tree source does describe the NPU blocks as `generic-uio`; those
  values are SDK material and stay out of this repository.
- **`/dev/cmem_other*`** — the contiguous-memory devices the runtime opens
  are served by an out-of-tree Renesas module, loaded once per boot. It is
  absent from the pinned kernel source and from this image's module tree, and
  the vendor's build is against their own kernel release, so it cannot simply
  be copied across; it is built from public source against this board's kernel
  tree instead ([npu-bringup.md](npu-bringup.md) pins the commit and explains
  why not HEAD). The module itself is no longer the gap — the `cmem_other`
  devices are, because their count and size come from a `/cmem` device-tree
  node this board does not have.
- **`/dev/npuc*`** — these are UIO devices, named the same way as every
  device in the table above: the vendor's NPU device tree declares them
  `generic-uio` with a `linux,uio-name`, and the userspace side selects their
  register windows by `mmap` offsets that are multiples of the page size,
  which is the UIO map-selection convention. So the drop-in here, and the udev
  rule above, are the mechanism the NPU will use; what is missing is only the
  nodes.

## Related

- [UFS self-boot](selfboot.md) — the boot path and why `bootargs` is
  expensive to change.
- [CR52 dual boot + RPMsg](rpmsg-dualboot.md) — the kernel-space RPMsg path,
  which is what the board uses today; `rpmsg_shm0`/`rpmsg_ipi0` are the
  userspace alternative the same hardware also exposes.
