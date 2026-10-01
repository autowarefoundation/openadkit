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

**Almost all of this chain now ships in the image, and the two pieces that do
not are staged by `scripts/stage-board.sh prepare-root`, not by hand.**
`aib/x5h-rootfs.aib.yml` installs `rpmsg-eth.service` (to
`/etc/systemd/system/`), its `ifup` helper to
**`/usr/sbin/rpmsg-eth-ifup.sh`**, and the whole `cr52-remoteproc` trio:
`cr52-rproc-up.sh` to **`/usr/sbin/cr52-rproc-up.sh`**,
`cr52-remoteproc.service` to `/etc/systemd/system/`, and
`x5h-rpmsg-modules.conf` to `/etc/modules-load.d/x5h-rpmsg.conf`.
`80-x5h.preset` enables `cr52-remoteproc.service`.

Exactly two files are still staged onto the board, and `stage-board.sh
prepare-root` injects both into the root image before it is written, so neither
is a live-board step any more:

- the `rpmsg-eth` daemon binary, into `/usr/local/bin/rpmsg-eth` (written as
  `/var/usrlocal/bin/rpmsg-eth` in the mounted image, because `/usr/local` is a
  symlink to `../var/usrlocal`), and
- the CR52 ELF, into `/lib/firmware/`, with a matching
  `CR52_FIRMWARE=` line written to `/etc/default/cr52-remoteproc`.

Both are staged rather than baked for the same reason: the board image ships no
compiler, and neither file is a repository artifact. The `cr52-*` and
`rpmsg-eth` commands in the blocks below are therefore no longer instructions
for a fresh board. Read them as the description of what the units do, which is
what you need when one of them misbehaves.

The `/usr/sbin` helper vs `/usr/local/bin` binary split is deliberate.
`automotive-image-builder` installs only under `/etc/`, `/usr/` or `/var/`
and refuses `/usr/local` outright — the build aborts with "Path
'/usr/local/…' is not allowed" — because this rootfs is ostree-structured
and ships `/usr/local` as a symlink to `../var/usrlocal` (see
[selfboot.md](selfboot.md), "A trap when staging files into the image").
So anything the **image** ships lives under `/usr`; anything the
**operator** stages by hand after boot lives under `/usr/local`, which is
the correct place for it at runtime. `cr52-rproc-up.sh` used to be hand-staged
under `/usr/local/sbin` for that reason; it is a repository script with no
build step, so it now ships in the image and lives at `/usr/sbin/cr52-rproc-up.sh`
like every other image-installed helper. The `rpmsg-eth` daemon is the piece
that genuinely cannot be baked, and it is the reason the split still exists.

`80-x5h.preset` deliberately does not enable `rpmsg-eth.service`, but that
does not keep the unit out of a normal boot: `components/awf-oak-bridge.container`
carries `Requires=rpmsg-eth.service` together with `[Install]
WantedBy=default.target`, so Quadlet auto-enables the bridge and the bridge
pulls the link up at boot whatever the preset says. The preset omission only
matters on boots where nothing else wants the link — an image without the
component stack, or a board where the bridge unit is disabled or masked.

What keeps an unstaged binary benign is `ConditionPathExists=/usr/local/bin/rpmsg-eth`
in the unit. Without it, `ExecStart` fails at once and `Restart=on-failure`
+ `RestartSec=1` + `StartLimitIntervalSec=0` retry forever at roughly 1 Hz
— an endless restart loop, not the single permanently-failed unit this
document used to claim. A condition that is not met is not a failure:
systemd logs one line naming the missing path, skips the unit, and reports
the start job as successful, so the bridge's `Requires=` is satisfied
cleanly.

The normal route is `stage-board.sh prepare-root`, which installs the binary
into the root image on the companion before that image is written to the board,
so a freshly imaged board already has it. The hand route below is for a board
that is already running and only needs a newer daemon. Stage it onto the NFS
export first (see "Staging the assets" above for why `/var/tmp`, not `/tmp`, is
the export path to use), then install it on the target:

```
install -m0755 rpmsg-eth <export>/var/tmp/rpmsg/
```

```
install -m0755 /var/tmp/rpmsg/rpmsg-eth /usr/local/bin/rpmsg-eth
systemctl daemon-reload
systemctl restart rpmsg-eth.service
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
both were repeated by hand. Two image-installed pieces make the link come up on
its own, so the manual commands above are a description of what they do rather
than something to remember:

- `/etc/modules-load.d/x5h-rpmsg.conf` loads `rpmsg_ctrl` and `rpmsg_char` at
  boot (source: `config/x5h-rpmsg-modules.conf`).
- `cr52-remoteproc.service` runs `/usr/sbin/cr52-rproc-up.sh`, which does the
  `start` write and polls for `running`. It is enabled by `80-x5h.preset` and
  carries `ConditionKernelCommandLine=x5h.role=cr52`, so it is skipped
  outright in the `npu` role. That gating is not optional: under the vendor NPU
  device tree `cr52_1`'s `memory-region` phandle resolves to no node and a
  `start` write panics the kernel by construction.

**A condition on `x5h.role=cr52` is not satisfied by "not the npu role": it is
also unsatisfied whenever `x5h.role=` is absent from the kernel command line
altogether.** That is not a corner case. `uboot/autosd-boot.env` builds
`bootargs_autosd` with no `x5h.role=` word, so every netboot rescue
(`run rescue_autosd`, `run bootcmd_autosd`) lands on a root with no role, and
so does any board that has not yet had the self-boot environment imported. The
NFS rescue root is extracted from the same image tar, so it carries all nine
role-gated units and skips every one of them; `/run/x5h/role` reads `unknown`
and `selfboot-smoke.sh` on such a root fails with
`SELFBOOT_SMOKE_FAIL reason=unknown_role role=unknown`, correctly. The
procedure above therefore does nothing on a netbooted root unless the role is
supplied by hand. Two ways to do that, in order of preference:

- Append `x5h.role=cr52` to the rescue bootargs before booting, which is what
  the self-boot roles do and what makes every unit behave identically to a
  self-boot:

  ```
  => setenv bootargs_autosd "${bootargs_autosd} x5h.role=cr52"
  => run bootcmd_autosd
  ```

  Re-enter the whole `setenv bootargs_autosd "..."` line rather than editing a
  component of it: `bootargs_autosd` is double-quoted in that file and has
  already expanded, so changing an input after the fact changes nothing.
- Or, on the already-booted rescue root, run the two commands at the top of
  this section by hand. They are the whole of what the unit does, and the
  unit's condition is the only thing standing in the way.

The netboot rescue is a first-class path in this branch's own workflow:
[selfboot.md](selfboot.md), "Staging a board", recommends `rescue_autosd`
precisely because it frees `x5h-root` for `write-root`. Do not read a rescue
boot with no units running as a regression in the units.

The one remaining input is the ELF, and `stage-board.sh prepare-root` installs
it together with its `CR52_FIRMWARE=` line while the root image is still on the
companion:

```
install -m0644 <the flashed firmware>.elf /lib/firmware/
printf 'CR52_FIRMWARE=%s\n' "<the flashed firmware>.elf" > /etc/default/cr52-remoteproc
```

The staged ELF **must** match what is flashed in the Core1 slot: `start` parses
the resource table out of it to publish the vrings, so a mismatch yields a link
that looks configured and passes nothing.

Leaving `CR52_FIRMWARE` unset is also valid: the driver's stock name is
`rproc-cr52_1-fw`, so a symlink at `/lib/firmware/rproc-cr52_1-fw` works just as
well. Either way the unit reports what it did — `CR52_RPROC_UP name=… firmware=…`,
or `CR52_RPROC_SKIP reason=no_firmware path=…` on a board where the ELF has not
been staged yet, which is the expected state on a freshly imaged board and is
deliberately not treated as a failure.

These three files used to be excluded from `aib/x5h-rootfs.aib.yml` on the
argument that the unit's `ExecStart` was a script the image did not carry, so
baking the unit in would leave every first boot with a failed unit. That
argument was resolved by shipping the script too: all three are in the manifest
now, and a board with no ELF staged yet reports
`CR52_RPROC_SKIP reason=no_firmware` and exits 0 rather than failing.

`rpmsg-eth.service` remains deliberately absent from `80-x5h.preset`, which is a
standing ruling and not an oversight. It is still reached on a normal `cr52`
boot, because `awf-oak-bridge.container` carries `Requires=rpmsg-eth.service`
and pulls it up.

### Smoke

```
/usr/sbin/rpmsg-eth-smoke.sh
```

The script ships in the image (`aib/x5h-rootfs.aib.yml`), so it is already on
any board written by `stage-board.sh write-root`; the repository copy is the
source, not something to copy across by hand.

Asserts the channel is on the rpmsg bus, `rpmsg-eth.service` is active,
`tap0` is up with the frozen address/MAC/MTU, then round-trip pings the
CR52 side requiring 100% reply. `-n` skips the rpmsg-bus channel assertion
for a bench run against a manually wired peer with no CR52 attached. See
the script's own header for the full `reason=` vocabulary on failure.
