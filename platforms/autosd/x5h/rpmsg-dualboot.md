# X5H dual boot: CR52 FreeRTOS under AutoSD, with RPMsg

Runs a FreeRTOS payload on the CR52 realtime core while AutoSD runs on
the CA720AE cluster, and exchanges RPMsg messages between them over the
kernel remoteproc/RPMsg stack.

The realtime payload is **not** loaded by Linux. It is flashed into the
realtime core's boot slot and started by the boot firmware, so it is
already executing before Linux comes up. `echo start` on the `cr52_1`
remoteproc only parses the resource table out of the staged ELF,
publishes the vrings into the CR52's reserved-memory carveout, and rings
the MFIS doorbell. This is the vendor-normative arrangement: on this SoC
`.load` and `.stop` are no-ops, so runtime loading through remoteproc is
not merely unsupported, it is not implemented.

## Status on real hardware

Validated on the board on 2026-08-07, on both the BSP Yocto reference
boot (`6.1.102-yocto-standard`) and AutoSD (`6.1.102-autosd`), with a
vendor-supplied CR52 RPMsg firmware built for **MFIS channel 1** flashed
into the realtime core's boot slot.

**Both OSes pass, with byte-identical marker lines:**

```
virtio_rpmsg_bus virtio0: creating channel rpmsg-client-sample addr 0x400
RPMSG_PING_PASS n=100 service=rpmsg-client-sample dst=0x400 mode=responder reply='Hello world from CR52/Free-RTOS!'
RPMSG_SMOKE_PASS cycles=1 msgs=100
```

The round trip is confirmed from both ends independently: Linux received
100 replies, all byte-identical, and the CR52's own console logged
`Incoming msg: x5h-rpmsg-ping seq=0` … `seq=99` — the exact sequenced
payloads `rpmsg-ping` sent. AutoSD produced no SELinux AVC denials and no
rpmsg/remoteproc errors.

| Check | Both OSes |
|---|---|
| `remoteproc0` name / state / default firmware | `cr52_1` / `offline` / `rproc-cr52_1-fw` |
| After `start` | `rpmsg host is online`, `remote processor cr52_1 is now up` |
| Announced channel | `rpmsg-client-sample` at `addr 0x400` |
| Round trips | 100/100, reply constant |

Zero AutoSD-vs-vendor-BSP delta: every observation on AutoSD matched the
Yocto reference exactly.

## What the kernel already provides

The 6.1.102-autosd image and `r8a78000-ironhide-uio-autosd.dtb` ship
with `CONFIG_RCAR_GEN5_REMOTEPROC=y`, `CONFIG_RCAR_MFIS=y`,
`CONFIG_RPMSG_VIRTIO=y` (`rpmsg_char`/`rpmsg_ctrl` as modules), the
`cr52_1` remoteproc node on MFIS channel 1, and its reserved-memory
carveout. Nothing needs rebuilding to use them.

Note that the device tree pins which realtime core is reachable, and
how. `cr52_1` is the only enabled remoteproc node (`cr52_0` and `cr52_2`
are `disabled`), and `renesas,mfis-channels` is a *list of channel
indices*, not a count — `<1>` registers channel 1 only. The
userspace-UIO alternative is wired the other way round: `rpmsg_shm0` /
`rpmsg_ipi0` (channel 0) are enabled while their channel-1 counterparts
are disabled. So on this device tree the kernel rpmsg_char path reaches
core 1 and nothing else, and a firmware flashed for a different channel
will never be serviced no matter how healthy the Linux side looks.

## Prerequisites

- A CR52 RPMsg firmware **flashed into the realtime core's boot slot**,
  built for this board with MFIS channel 1 — the channel must match the
  device tree, and the firmware's `.resource_table` address must equal
  the `memory-region` of the `cr52_1` node. Flashing is a separate,
  operator-authorised step: it writes vendor flash and is out of scope
  for this document.
- The **same** firmware ELF staged as `/lib/firmware/rpmsg-echo-cr52.elf`
  on the target rootfs. Only its `.resource_table` is consumed — the
  code and data segments are never copied to the core — but it is what
  Linux derives the vring layout from, so a stale ELF that no longer
  matches the flashed image will disagree about the ring layout.
- `rpmsg-ping` (static aarch64, built from `scripts/rpmsg-ping.c`) and
  `scripts/rpmsg-smoke.sh` on the target. `rpmsg-smoke.sh` resolves
  `rpmsg-ping` relative to its own directory first, falling back to
  `PATH`, so `rpmsg-ping` must be executable and either sit next to
  `rpmsg-smoke.sh` or be reachable on `PATH`.

### Staging the assets

Both rootfs images netboot over NFS, so the host can drop files straight
into the export instead of copying them to a running board. `/tmp` is a
tmpfs on *both* the BSP Yocto and the AutoSD rootfs, so anything written
to `<export>/tmp` from the host is invisible on the target — use a path
that is not a mount point. On AutoSD, `/var/tmp` is a plain directory on
the NFS root and works:

```
install -m0755 rpmsg-ping rpmsg-smoke.sh <export>/var/tmp/rpmsg/
install -m0644 rpmsg-echo-cr52.elf        <export>/var/tmp/rpmsg/
```

then, on the target (the exports are `no_root_squash`, so board-side
root can write anywhere on them):

```
install -m0755 /var/tmp/rpmsg/rpmsg-ping /var/tmp/rpmsg/rpmsg-smoke.sh /usr/local/bin/
install -m0644 /var/tmp/rpmsg/rpmsg-echo-cr52.elf /lib/firmware/
```

If only one export is writable from the host, the board can reach the
other one itself: NFS-mount it from the target with an explicit
`-o vers=3,addr=<host>` (both options are required here — without
`vers=3` the mount fails with `NFS: Version unavailable`) and copy
across.

## Procedure

1. Power on. The realtime firmware starts from flash before Linux; its
   console (a separate serial channel from the Linux console, 115200)
   should show the OpenAMP banner ending in `creating remoteproc virtio`.
   If that banner is absent, stop — nothing will answer, and the Linux
   side cannot tell you why.
2. Boot the target OS (BSP Yocto default boot, or AutoSD via
   `run bootcmd_autosd` netboot).
3. Block the in-tree sample driver from taking the channel — see Notes
   for why this must happen *before* the first `start`:
   ```
   echo 'blacklist rpmsg_client_sample' > /etc/modprobe.d/x5h-rpmsg-diag.conf
   modprobe rpmsg_ctrl && modprobe rpmsg_char
   ```
4. Preflight (read-only): `sh rpmsg-smoke.sh --check`
   — confirms the `cr52_1` remoteproc exists, reports its state, and
   ends with the `RPMSG_SMOKE_CHECK_DONE` marker. Any problem found
   before that point instead prints `RPMSG_SMOKE_FAIL cycle=0
   reason=<...>` and exits 1; `--check` makes no state changes either
   way.
5. Smoke: `sh rpmsg-smoke.sh -f rpmsg-echo-cr52.elf \
   -s rpmsg-client-sample -n 100`
6. A working run prints `RPMSG_PING_PASS n=100 ...` and
   `RPMSG_SMOKE_PASS cycles=1 msgs=100`. A failing cycle instead prints
   `RPMSG_SMOKE_FAIL cycle=<i> reason=<...>` and the script exits 1.

**One session per boot.** The CR52 firmware creates and announces its
RPMsg endpoint exactly once per reset. After the smoke's closing `stop`,
a further `start` brings the Linux vdev back up but the channel is never
re-announced, so a second cycle can only ever end in `service_timeout`.
That is why `-c` defaults to 1; running the smoke again needs a hardware
reset or power cycle, not a `stop`/`start`. A soft `reboot` of Linux does
*not* reset the realtime core.

## Notes

- `start` and `stop` do not touch the CR52. The SoC's remoteproc driver
  implements `.load` and `.stop` as no-ops and `.start` only validates
  the boot address; there is no reset, clock, or firmware handoff in it,
  and `auto_boot` is false with no `.attach`. So the reported `state`
  describes the Linux-side vdev, not the core: it reads `offline` at
  boot on both OSes whether or not the CR52 is executing something.
  Treat `state` as "has Linux published the vrings", never as "is the
  remote alive". The realtime console is the only direct read on the
  core's health.
- `reason=service_timeout` after a successful `start` means no remote
  announced the channel. Check the realtime console first: a silent one
  means the flashed payload is not running or was built for a different
  MFIS channel, and no amount of Linux-side work will fix it.
- If a `start` logs `rcar_gen5_rproc_kick failed`, the MFIS doorbell
  rung by an earlier `start` was never acknowledged — the kick helper
  refuses to ring again while the remote is still flagged as processing
  the previous interrupt, and only the remote clears that flag. That is
  a positive indication that nothing is servicing the channel, which is
  stronger than a timeout alone.
- `rpmsg-ping` has two reply modes because two remote protocols exist.
  The default *responder* mode fits the vendor firmware, which answers
  every request with the same constant string; it requires a non-empty
  reply per request and that every reply be byte-identical to the first,
  so a corrupted or mis-sequenced vring still fails. `-e` selects strict
  *echo* mode, where each reply must match the payload that was sent —
  use it only against a firmware that really echoes, or every request
  will fail as `payload_mismatch`.
- The kernel ships an in-tree `rpmsg_client_sample` sample driver,
  staged as a module in both the BSP Yocto and AutoSD modules trees,
  that binds a channel named exactly `rpmsg-client-sample` and runs its
  own message exchange if loaded. Both trees carry the matching
  `alias rpmsg:rpmsg-client-sample` in `modules.alias`, and the rpmsg
  bus announces a `MODALIAS` on every channel add, so under
  systemd-udevd this module auto-loads on *every* smoke cycle, not just
  once at boot — unloading it once does not stop it coming back on the
  next cycle. Blacklist it before the first `start` (procedure step 3);
  a rootfs file, no flash write. To check:
  ```
  lsmod | grep rpmsg_client_sample
  ```
  If it wins the channel before it is blocked, the damage outlives an
  `rmmod`: OpenAMP binds the endpoint's destination address to the first
  remote sender and never re-binds, so the CR52 keeps replying to the
  sample driver's address and `rpmsg-ping` sees `rx_timeout` on `seq=0`
  even after the module is gone. Because `stop`/`start` do not touch the
  CR52 (see above), only a CR52-side restart clears this.
- Catching the U-Boot prompt on a warm `reboot` needs a tighter key spam
  than a cold power-on does. The autoboot countdown is about 2.5 s ("Hit
  any key to stop autoboot: 2 1 0"); Enter every 300 ms missed it
  outright, Enter every 80 ms caught it in 75 keystrokes.
- Recovery from any wedge: power cycle. This procedure modifies no boot
  path and writes no flash; the only persistent state it creates is the
  staged files and the blacklist on the target rootfs.
