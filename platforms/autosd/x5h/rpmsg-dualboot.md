# X5H dual boot: CR52 FreeRTOS under AutoSD, with RPMsg

Runs a FreeRTOS payload on the CR52 realtime core while AutoSD runs on
the CA720AE cluster, using the kernel remoteproc/RPMsg stack. No flash
is written by this procedure: `echo start` on the `cr52_1` remoteproc
publishes the resource table into the CR52's reserved-memory carveout,
allocates the vrings, and enables the MFIS doorbell for a CR52 that is
already executing — it does not load an ELF onto the core or release
it from reset. A power cycle always returns the board to its default
boot.

## Status on real hardware

Validated on the board on 2026-08-06, on both the BSP Yocto reference
boot (`6.1.102-yocto-standard`) and AutoSD (`6.1.102-autosd`).

**The Linux side works and is identical on both OSes.** The `cr52_1`
remoteproc enumerates, accepts a firmware name, goes `offline` →
`running`, and brings up a working virtio RPMsg bus:

| Check | Both OSes |
|---|---|
| `remoteproc0` name / state / default firmware | `cr52_1` / `offline` / `rproc-cr52_1-fw` |
| Probe log | `rcar_mfis: channel 1 initialized`, `mfis-mbox: MFIS mailbox enabled with 2 chans`, `remoteproc0: cr52_1 is available` |
| After `start` | `virtio_rpmsg_bus virtio0: rpmsg host is online`, `remote processor cr52_1 is now up` |
| `virtio0` status | `0x07` (ACKNOWLEDGE \| DRIVER \| DRIVER_OK) |
| rpmsg bus | `virtio0.rpmsg_ctrl.0.0`, `virtio0.rpmsg_ns.53.53`, `/dev/rpmsg_ctrl0` |
| SELinux (AutoSD, permissive) | no AVC denials touching rpmsg / remoteproc / firmware |

**The echo round trip does not work, because nothing is running on the
CR52 to answer it.** Both OSes stop at:

```
RPMSG_SMOKE_FAIL cycle=1 reason=service_timeout service=rpmsg-client-sample
```

A second `start` in the same boot then logs:

```
rcar-gen5-rproc soc:cr52_1: rcar_gen5_rproc_kick failed
```

which is the decisive evidence. That message means the MFIS doorbell
rung by the *first* `start` was never acknowledged: the kick helper
refuses to ring again while the remote is still flagged as processing
the previous interrupt, and the remote only clears that flag when it
services the doorbell. So the CR52 is not servicing MFIS channel 1 at
all — it is not merely missing an RPMsg service.

Getting an RPMsg-capable payload onto the CR52 requires writing its
boot-firmware flash slot, which the zero-flash-write rule this work is
held to forbids. There is no software path around it: the SoC's
remoteproc driver does not load or start the core (see Notes), and
U-Boot on this board has no remoteproc support either — `help rproc`
returns `Unknown command`, and the command list has no `rproc`, no
`cpu`, and nothing else CR52-related. Loading the ELF from RAM at the
U-Boot prompt is therefore not an option.

**What this means for a failing run:** a `reason=service_timeout` on
this board is the *expected* result today. It is neither a defect in
this tooling nor an AutoSD regression — the AutoSD result is
byte-for-byte the same as the vendor BSP reference. Do not open a
vendor escalation on the strength of a `service_timeout` alone.

## What the kernel already provides

The 6.1.102-autosd image and `r8a78000-ironhide-uio-autosd.dtb` ship
with `CONFIG_RCAR_GEN5_REMOTEPROC=y`, `CONFIG_RCAR_MFIS=y`,
`CONFIG_RPMSG_VIRTIO=y` (`rpmsg_char`/`rpmsg_ctrl` as modules), the
`cr52_1` remoteproc node on MFIS channel 1, and its reserved-memory
carveout. Nothing needs rebuilding to use them.

## Prerequisites

- A CR52 firmware ELF staged as `/lib/firmware/rpmsg-echo-cr52.elf` on
  the target rootfs, built for this board with MFIS channel 1 — the
  channel must match the device tree. Only its `.resource_table`
  segment is consumed: the remoteproc driver's `.load` is a no-op, so
  the ELF's code and data segments are never copied to the core. The
  ELF supplies the vring layout Linux publishes into the carveout; the
  code that would answer on the other end has to already be running on
  the CR52.
- `rpmsg-ping` (static aarch64, built from `scripts/rpmsg-ping.c`;
  takes `-s <service>`, `-n <count>`, and `-t <timeout_s>`) and
  `scripts/rpmsg-smoke.sh` on the target. `rpmsg-smoke.sh` resolves
  `rpmsg-ping` relative to its own directory first, falling back to
  `PATH`, so `rpmsg-ping` must be executable and either sit next to
  `rpmsg-smoke.sh` or be reachable on `PATH`.

### Staging the assets

Both rootfs images netboot over NFS, so the host can drop files
straight into the export instead of copying them to a running board.
`/tmp` is a tmpfs on *both* the BSP Yocto and the AutoSD rootfs, so
anything written to `<export>/tmp` from the host is invisible on the
target — use a path that is not a mount point. On AutoSD, `/var/tmp`
is a plain directory on the NFS root and works:

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

## Procedure

1. Boot the target OS (BSP Yocto default boot, or AutoSD via
   `run bootcmd_autosd` netboot).
2. Block the in-tree sample driver from taking the channel — see Notes
   for why this must happen *before* the first `start`:
   ```
   echo 'blacklist rpmsg_client_sample' > /etc/modprobe.d/x5h-rpmsg-diag.conf
   ```
3. Preflight (read-only): `sh rpmsg-smoke.sh --check`
   — confirms the `cr52_1` remoteproc exists, reports its state, and
   ends with the `RPMSG_SMOKE_CHECK_DONE` marker. Any problem found
   before that point instead prints `RPMSG_SMOKE_FAIL cycle=0
   reason=<...>` and exits 1; `--check` makes no state changes either
   way.
4. Single-cycle probe: `sh rpmsg-smoke.sh -f rpmsg-echo-cr52.elf \
   -s rpmsg-client-sample -n 100 -c 1` — one load/start/ping/stop round
   trip. Run `-c 1` first, always: on the board today this stops at
   `reason=service_timeout` (see Status), and a multi-cycle run adds
   nothing until that is resolved.
5. Multi-cycle probe, only once step 4 passes: `sh rpmsg-smoke.sh \
   -f rpmsg-echo-cr52.elf -s rpmsg-client-sample -n 100 -c 3` — probes
   whether the CR52 survives repeated Linux-side vdev teardown, which
   is a different question from step 4. Because `stop` is a no-op on
   this SoC (see Notes), a cycle boundary only tears down the Linux
   side: the CR52 keeps its ring indices and its already-bound
   endpoint while Linux allocates fresh vrings with reset indices on
   the next `start`. A failure at cycle 2 or later is therefore an
   expected, non-blocking outcome of that mismatch, not a regression —
   treat a passing step 4 as the meaningful result and don't escalate
   on a later-cycle failure by itself.
6. A working run prints `RPMSG_PING_PASS n=100 ...` per cycle and a
   final `RPMSG_SMOKE_PASS cycles=<c> msgs=100`. A failing cycle
   instead prints `RPMSG_SMOKE_FAIL cycle=<i> reason=<...>` and the
   script exits 1.

## Notes

- `start` and `stop` do not touch the CR52. The SoC's remoteproc
  driver implements `.load` and `.stop` as no-ops and `.start` only
  validates the boot address; there is no reset, clock, or firmware
  handoff in it, and `auto_boot` is false with no `.attach`. So the
  reported `state` describes the Linux-side vdev, not the core: it
  reads `offline` at boot on both OSes whether or not the CR52 is
  executing something. Treat `state` as "has Linux published the
  vrings", never as "is the remote alive".
- `reason=service_timeout` after a successful `start` means no remote
  announced the channel. See Status above for what that currently
  indicates on this board and why it is not an escalation trigger on
  its own.
- The kernel ships an in-tree `rpmsg_client_sample` sample driver,
  staged as a module in both the BSP Yocto and AutoSD modules trees,
  that binds a channel named exactly `rpmsg-client-sample` and runs
  its own message exchange if loaded. Both trees carry the matching
  `alias rpmsg:rpmsg-client-sample` in `modules.alias`, and the rpmsg
  bus announces a `MODALIAS` on every channel add, so under
  systemd-udevd this module auto-loads on *every* smoke cycle, not
  just once at boot — unloading it once does not stop it coming back
  on the next cycle. Blacklist it before the first `start`
  (procedure step 2); a rootfs file, no flash write. To check:
  ```
  lsmod | grep rpmsg_client_sample
  ```
  If it wins the channel before it is blocked, the damage outlives an
  `rmmod`: OpenAMP binds the endpoint's destination address to the
  first remote sender and never re-binds, so the CR52 keeps echoing to
  the sample driver's address and `rpmsg-ping` sees `rx_timeout` on
  `seq=0` even after the module is gone. Because `stop`/`start` do not
  touch the CR52 (see above), only a CR52-side restart clears this — a
  Linux-side `stop`/`start` cycle will not.
- Catching the U-Boot prompt on a warm `reboot` needs a tighter key
  spam than a cold power-on does. The autoboot countdown is about
  2.5 s ("Hit any key to stop autoboot: 2 1 0"); Enter every 300 ms
  missed it outright, Enter every 80 ms caught it in 75 keystrokes.
- Recovery from any wedge: power cycle. The default boot path is never
  modified by this procedure.
