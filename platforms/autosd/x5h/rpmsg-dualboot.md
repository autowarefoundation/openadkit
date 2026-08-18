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
That is why `-c` defaults to 1: what a second run needs is a reset of the
realtime core, and a `stop`/`start` is not one (see the first bullet under
Notes). It does **not** need physical access, though — a plain `reboot`
from Linux is enough. Linux issues PSCI `SYSTEM_RESET`, the firmware
implements it as a graceful cold reset, and the CR52 restarts and re-loads
its flashed payload along with the APU; that was observed on every warm
reboot from both Yocto and AutoSD. See
[selfboot.md](selfboot.md#reset-behaviour-and-what-restarts-the-realtime-core).

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

## rpmsg-eth: IP-over-RPMsg bridge

`rpmsg-eth/` (source `rpmsg-eth.c`, `Makefile`, `test-rpmsg-eth.sh`) bridges
the CR52's `rpmsg-eth` rpmsg channel to a Linux TAP device (`tap0`), one
Ethernet frame per RPMsg message in both directions — a normal IP link to
the safety island, on top of the same remoteproc/RPMsg stack described
above. Frozen wire constants: service name `rpmsg-eth`; MTU **462** / max
frame 476 (see `scripts/rpmsg-eth-ifup.sh`); Linux side `172.16.52.1/24`,
MAC `02:5c:52:00:00:01`; CR52 side `172.16.52.2/24`, MAC
`02:5c:52:00:00:02`; DDS domain 2. The CR52 uses lwIP's `etharp`
(`NETIF_FLAG_ETHARP`) and resolves peers dynamically, so ARP passes
through untouched — neither side needs a static peer table.

### Building (cross-compile)

The board image ships no compiler (see the AutoSD rootfs manifest,
`aib/x5h-rootfs.aib.yml` — no `gcc`/`make`), so `rpmsg-eth` is built on the
host and staged as a binary, the same pattern as `scripts/rpmsg-ping.c`.
`rpmsg-eth/Makefile` defaults to `CC ?= cc` with `LDFLAGS ?= -static`
(static so the one binary runs unmodified on both the BSP Yocto and the
AutoSD NFS rootfs); override `CC` for an aarch64 target from an x86_64 dev
host, e.g. with a distro `aarch64-linux-gnu-gcc` cross toolchain and its
static libc package installed:

```
cd rpmsg-eth
CC=aarch64-linux-gnu-gcc make
```

This is a plain host build, unrelated to and independent from the pinned
ARM GNU 13.2 toolchain used for the *kernel* rebuild above — that pin
exists because of a board-specific boot-time layout bug in the kernel
Image; it has no bearing on a static userspace binary. (CI instead builds
`rpmsg-eth` natively inside an `arm64`-platform Fedora container — see
`scripts/make-test-images.sh` — because that container also needs to run
the binary it builds, on the same architecture, for `test-rpmsg-eth.sh`;
that path is CI-only and not a stand-in for a documented cross-compile
invocation for staging onto the board.)

### Staging

`aib/x5h-rootfs.aib.yml` installs `rpmsg-eth.service` and its `ifup` helper
(`rpmsg-eth-ifup.sh`) today. Only the daemon binary is not — same manual
install-to-`/usr/local` pattern as `rpmsg-ping`/`rpmsg-smoke.sh` above, and
the same reason: the board image ships no compiler, so nothing built from
source lands there except by hand (see "Building" above). `80-x5h.preset`
deliberately does not enable `rpmsg-eth.service`: enabling it before the
binary is staged would add a second permanently-failed unit to the
board's documented steady state. Stage the daemon onto the NFS export (see
"Staging the assets" above for why `/var/tmp`, not `/tmp`, is the export
path to use), then install it on the target:

```
install -m0755 rpmsg-eth <export>/var/tmp/rpmsg/
```

```
install -m0755 /var/tmp/rpmsg/rpmsg-eth /usr/local/bin/rpmsg-eth
systemctl daemon-reload
systemctl enable --now rpmsg-eth.service
```

### Prerequisites

`rpmsg-eth.service` has no `After=`/`Wants=` on a specific rpmsg device
unit — the daemon's own endpoint-wait loop already retries until the
CR52's channel appears (logging its progress; see `rpmsg-eth.c`) — but it
does **not** load the rpmsg modules or start `remoteproc0` for you. Both
must already be done, exactly as in the Procedure above:

```
modprobe rpmsg_ctrl && modprobe rpmsg_char
echo start > /sys/class/remoteproc/remoteproc0/state
```

Starting the unit before either of those has happened is not an error —
the daemon waits and retries rather than failing — but it means the link
will never come up until they are done, so do them first rather than
relying on the retry to eventually paper over a skipped step.

**Neither of those two steps survives a reboot**, which was board-confirmed
during the Stage 2 session: after a warm reboot the modules were unloaded and
`remoteproc0` was back to `offline`, so the link stayed down (with the daemon
correctly logging `no channel named 'rpmsg-eth' on the rpmsg bus yet`) until
both were repeated by hand. Install the two helpers below to make the link come
up on its own, and the manual commands above become a description of what they
do rather than something to remember:

```
install -m0755 cr52-rproc-up.sh          <export>/var/tmp/rpmsg/
install -m0644 cr52-remoteproc.service   <export>/var/tmp/rpmsg/
install -m0644 x5h-rpmsg-modules.conf    <export>/var/tmp/rpmsg/
```

```
install -m0755 /var/tmp/rpmsg/cr52-rproc-up.sh /usr/local/sbin/cr52-rproc-up.sh
install -m0644 /var/tmp/rpmsg/cr52-remoteproc.service /etc/systemd/system/cr52-remoteproc.service
install -m0644 /var/tmp/rpmsg/x5h-rpmsg-modules.conf /etc/modules-load.d/x5h-rpmsg.conf
# Point remoteproc at the ELF matching what is flashed in the Core1 slot. The
# staged ELF MUST match the flashed image: `start` parses the resource table out
# of it to publish the vrings, so a mismatch yields a link that looks configured
# and passes nothing.
install -m0644 <the flashed firmware>.elf /lib/firmware/
printf 'CR52_FIRMWARE=%s\n' "<the flashed firmware>.elf" > /etc/default/cr52-remoteproc
systemctl daemon-reload
systemctl enable --now cr52-remoteproc.service
```

Leaving `CR52_FIRMWARE` unset is also valid: the driver's stock name is
`rproc-cr52_1-fw`, so a symlink at `/lib/firmware/rproc-cr52_1-fw` works just as
well. Either way the unit reports what it did — `CR52_RPROC_UP name=… firmware=…`,
or `CR52_RPROC_SKIP reason=no_firmware path=…` on a board where the ELF has not
been staged yet, which is the expected state on a freshly imaged board and is
deliberately not treated as a failure.

Like the daemon, these three files are **not** installed by
`aib/x5h-rootfs.aib.yml`. That is intentional rather than an omission: the unit's
`ExecStart` is a script that ships in this repo, not in the image, so baking the
unit in while the script was absent would leave every first boot with a failed
unit and nothing gained. The whole `rpmsg-eth` stack is staged together.

```
systemctl enable --now rpmsg-eth.service
```

### Smoke

```
scripts/rpmsg-eth-smoke.sh
```

Asserts the channel is on the rpmsg bus, `rpmsg-eth.service` is active,
`tap0` is up with the frozen address/MAC/MTU, then round-trip pings the
CR52 side requiring 100% reply. `-n` skips the rpmsg-bus channel assertion
for a bench run against a manually wired peer with no CR52 attached. See
the script's own header for the full `reason=` vocabulary on failure.
