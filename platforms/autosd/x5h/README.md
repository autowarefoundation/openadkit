# AutoSD on R-Car X5H (Strategy A: BSP kernel + AutoSD userspace)

Non-ostree AutoSD 10 rootfs for the R-Car X5H (`r8a78000` / `ironhide`) board,
netbooted (TFTP kernel + NFS root) under either of two kernels that share the
same NFS root: the unmodified Renesas BSP kernel 6.1.102, or a rebuilt
`6.1.102-autosd` kernel built from the same public BSP source with SELinux,
`EXT4_FS_SECURITY`, nftables, EROFS and dm-verity compiled in (see "Rebuilt
kernel (6.1.102-autosd)" below). Validated off-board first by a QEMU gate that
boots the rootfs under the same-lineage kernel image the board netboots (one
build, two images: the board's copy additionally embeds the mp_phy firmware —
see "One build, two images" below) — so every container-runtime question is
answered before board time.

> **Where the gate runs.** The gate's CI workflow is not in this repository. It
> needs an arm64 runner large enough to boot an aarch64 guest under TCG, and an
> x64 runner large enough to compile the kernel, neither of which this
> repository provides, so it lives on the fork the platform was developed on —
> `youtalk/openadkit`, `.github/workflows/autosd-x5h-rootfs.yaml`. Everything
> the gate *runs* is here, under `scripts/` and `kernel/`, and replays on a dev
> host; the sections below that refer to "CI" or pass `--repo youtalk/openadkit`
> mean that fork's runs. Board bring-up is manual either way — no CI has the
> hardware.

- [CR52 dual boot + RPMsg](rpmsg-dualboot.md) — run FreeRTOS on the
  realtime core under AutoSD; remoteproc `start` publishes RPMsg state to
  a CR52 that is already executing, it does not load or release it. Also
  covers `rpmsg-eth`, the IP-over-RPMsg TAP bridge daemon (`rpmsg-eth/`)
  that gives the CR52 a normal Ethernet link to Linux.
- [UFS self-boot](selfboot.md) — boot AutoSD unattended from the board's
  own storage, with both netboots kept as named rescue commands; also the
  reset semantics, including why a warm `reboot` restarts the CR52.
- [CR52 slot update](cr52-slot-update.md) — replace the realtime firmware
  by writing its boot slot from Linux, instead of the vendor serial-download
  tool and a trip to the board.
- [Companion host](companion-host.md) — always-on bench gateway that keeps
  the board reachable remotely and scopes external developers' access.
  Executed and verified on hardware, 2026-08-10.
- [UIO](uio.md) — hand the SoC's accelerator blocks to userspace; why
  `uio_pdrv_genirq` comes up loaded and bound to nothing without an `of_id`,
  and how the bound blocks get `/dev` names a runtime can open.
- [NPU bring-up](npu-bringup.md) — reach the NPU from AutoSD through the
  ONNX Runtime Renesas execution provider: what the runtime needs, which
  steps need no flash write, and which two writes would break the CR52
  round trip and the self-boot partitions.
- [Component stack](component-stack.md) — the Open AD Kit MRM demo as five
  Quadlet units, with the trajectory follower on the CR52 (issue #120 M7):
  staging, unit ordering, the three smoke modes and the MRM-chain oracle,
  and why the scenario's junit is red on a healthy board.
- [MRM before/after demo](mrm-before-after-demo.md) — the CES-style
  before/after comparison on this board: two CR52 actuation parameter
  profiles, one scenario, stop distances compared by the companion-host
  orchestrator.

## Folder Structure

- `aib/`: automotive-image-builder manifest (distro `autosd10-sig`)
- `config/`: files shipped into the image — containers.conf drop-ins (base)
  or staged alongside the rebuilt kernel (`60-nftables.conf`), plus the
  self-boot set: key-only sshd drop-in, `authorized_keys`, the
  NetworkManager drop-in keeping `tsn5` kernel-managed, static resolvers,
  the rpmsg sample-driver blacklist, the `uio_pdrv_genirq` `of_id` binding
  and its udev naming rules (see [uio.md](uio.md)), the `rpmsg-eth.service`
  host unit, the `tmpfiles.d` fragment that creates the stack's scenario
  directory, and `80-x5h.preset`, which enables `sshd.service` and nothing
  else —
  deliberately not `rpmsg-eth.service`, which `awf-oak-bridge` pulls in
  itself (see [rpmsg-dualboot.md](rpmsg-dualboot.md)), and deliberately not
  the five Quadlet units, which Quadlet enables itself from their
  `[Install]` sections (all but `awf-oak-simulator`, which has none so that
  no scenario runs at boot)
- `kernel/`: rebuilt-kernel config fragments + build script, shared by the
  QEMU gate and the board — one build, two images: both boot an
  `Image-autosd` from the same source SHA, toolchain and fragments, and the
  only permitted config delta is the `CONFIG_EXTRA_FIRMWARE` pair (see "One
  build, two images")
- `ai/`: host-side inputs for the NPU compiler and the board-side accuracy
  check (see [ai/README.md](ai/README.md))
- `components/`: the Autoware stack as Quadlet units (issue #120 M7) — five
  `.container` units, all `Network=host` and none of them a pod member:
  `awf-oak-autoware` (the whole Autoware stack in one monolithic image,
  running `planning_simulator.launch.xml`), `awf-oak-simulator` (the
  scenario runner), `awf-oak-bridge` (`domain_bridge`), `awf-oak-relay` and
  `awf-oak-restamp` (the two Python nodes the CR52 link needs). Alongside
  them: the shared `awf-oak-x5h.env` every unit reads, the
  `cyclonedds-x5h.xml` that splits DDS domain 1 (Autoware, host network)
  from domain 2 (the CR52 safety island over `tap0`), the `launch/` control
  stub the Autoware unit mounts over the image's own copy,
  `scenario/mrm-scenario.yaml` (the MRM test definition; its 39 MB map is
  staged to the board separately by `scripts/stage-scenario-map.sh`, not
  committed — both map-consuming units carry `ConditionPathExists=` on the
  two files, so a board without them skips those units rather than hanging
  in `INITIALIZING`), `nodes/` (the relay and
  restamp sources, bind-mounted rather than baked), `images.txt` (the
  digest-pinned arm64 image set `scripts/stage-container-images.sh` stages
  onto the board), and `bridge/` — the `domain_bridge` container that joins
  the two domains, including its own build recipe. The unit set is a Quadlet
  translation of the working CES2026 demo of this topology; the
  compose-service-to-unit mapping, the exhaustive list of deviations from
  it, and the repo-subdirectory-to-flat-board-path rule for every mounted
  asset are all recorded at the top of `awf-oak-x5h.env`
- `scripts/`: QEMU gate harness and board staging/smoke scripts
- `rpmsg-eth/`: the IP-over-RPMsg TAP bridge daemon (source, Makefile, and
  its own pty-mock unit test) — see [rpmsg-dualboot.md](rpmsg-dualboot.md)
  for cross-compile, staging, prerequisites and smoke
- `uboot/`: `bootcmd_autosd` template (site values are filled at session
  time, not committed), and `selfboot-env.txt` — the `env import -t` payload
  defining the UFS self-boot plus both netboot rescue commands

## QEMU gate semantics

The gate boots the rootfs export under the same-lineage kernel image the
board netboots — `Image-autosd`, produced by `kernel/build-bsp-kernel.sh`
(one build, two images: the board's copy additionally embeds the mp_phy
firmware — see "One build, two images" in "Rebuilt kernel
(6.1.102-autosd)" below) — logs in as root, runs `scripts/gate-guest.sh`
inside the guest, and judges the run by grepping the session log for a
fixed set of markers.
`gate-guest.sh` emits the markers; `qemu-gate.exp` judges them by string
match — the two must stay in exact sync.

`gate-guest.sh` never exits nonzero mid-way: every assertion prints a marker
and `GATE_DONE` always prints, no matter which gates failed. All judgement
happens on the host side (`qemu-gate.exp`), by grepping the captured log for
these markers. Gate numbers are stable identifiers, not a sequence: GATE5 is
retired (see below) and deliberately not reused by the markers that replaced
it.

`GATE3_STORE_FS=tmpfs` and `GATE4_STORE_FS=btrfs` exist because GATE3/GATE4's
mount step (`mount -t tmpfs …` / `mkfs.btrfs` + `mount /dev/vdb …`) checks no
exit status and `gate-guest.sh` never aborts on a failed mount — without this
check, a silently-failed mount would leave `/var/lib/containers` on whatever
was mounted there before (typically the ext4 root), and the podman probe that
follows would still validly pass or fail, just against the wrong filesystem,
printing a `GATE3_TMPFS_OK` / `GATE4_BTRFS_OK` that didn't actually exercise
tmpfs/btrfs at all.

`qemu-gate.exp` exits 0 only once every required marker in the "Gate markers
(rebuilt-kernel edition)" table below (in "Rebuilt kernel (6.1.102-autosd)")
is present in the session log, and both `GATE1_MODPROBE_FAIL` and
`GATE1_CCVER_FAIL` are absent from it.

`qemu-gate.exp` waits for the guest-side run with an inactivity timeout (15
minutes with no new `GATE<n>_…` marker line, re-armed on every marker) rather
than one fixed budget for the whole run: the run's total length varies with
TCG emulation speed and isn't a meaningful thing to cap as a single number,
but a guest that goes genuinely silent, or dies outright, still fails fast
with a clear diagnostic instead of a generic "gate did not finish". The
15-minute figure is not arbitrary, and it is re-derived from the current
gate's markers, not carried over from the retired GATE5 arithmetic: GATE6 is
now the longest stretch with no re-arming marker output — its nftables
published-port poll (30 iterations of `curl --max-time 5` + `sleep 2`) caps
at 210s, and its outbound-SNAT poll (5 iterations of a busybox `podman run …
wget -T 10` + `sleep 2`) caps at roughly 60s more — comfortably under the
retired GATE5's two-loop worst case (~590s). See the
comment at `qemu-gate.exp`'s `inactivity_timeout` declaration for the full
arithmetic; the value itself (900s) is unchanged, only what it is derived
from.

### Gate markers (BSP-mimic edition, retired)

What follows is the historical marker vocabulary for the retired
BSP-constraint-mimic kernel gate — a 6.1.y LTS kernel carrying the same
feature gaps as the BSP kernel (no SELinux, no ext4 security xattrs, no
nftables, no erofs), boot-tested before the rebuilt kernel below replaced
it. Kept as the record of what that gate proved, not as current behavior —
see "Gate markers (rebuilt-kernel edition)" in "Rebuilt kernel
(6.1.102-autosd)" below for the gate this repository actually runs today.

Marker vocabulary (greppable, consumed by CI and quoted verbatim into each
run's results record):

| Marker | Meaning |
| --- | --- |
| `GATE1_LOGIN_OK` | Guest login succeeded. |
| `GATE1_SYSTEMD_STATE=<state>` | `systemctl is-system-running` output, informational. **`degraded` is expected** on this gate/kernel combination — see the Troubleshooting row for the two specific units that account for it. |
| `GATE2_STORE_FS=<fstype>` | Filesystem podman's store actually sat on for the GATE2 probe (expected `ext4`, since GATE2 mounts nothing). Informational — recorded so a reader can see what the GATE2 verdict was measured against, not gated on. |
| `GATE2_EXT4_FAIL_OK` | Podman image load on the ext4 root either failed outright with an unsupported-xattr error, or `load` reported success but a follow-up `getcap` inside a running container did not find the capability — either way, the capability did not survive onto ext4, confirming the `EXT4_FS_SECURITY` blocker. |
| `GATE2_EXT4_FAIL_OTHER` | Podman image load on the ext4 root failed for an unrelated reason. |
| `GATE2_EXT4_UNEXPECTED_PASS` | Podman image load on the ext4 root succeeded **and** the capability was confirmed readable via `getcap` inside a running container — a verified pass, not just a `load` that happened to exit 0 (see the GATE2/GATE3/GATE4 asymmetry row in Troubleshooting for why the `getcap` step matters here). |
| `GATE3_STORE_FS=<fstype>` | Filesystem podman's store actually sat on for the GATE3 probe. **Required to equal `tmpfs`** — otherwise a silently-failed tmpfs mount could fall through to the ext4 root underneath and still print `GATE3_TMPFS_OK` for the wrong reason. |
| `GATE3_TMPFS_OK` | Podman container store on tmpfs works, including the capability xattr round-trip. |
| `GATE3_FAIL` | The tmpfs-store probe failed. Not part of the pass path; printed instead of `GATE3_TMPFS_OK` so a human reading the raw log sees why that marker is missing. |
| `GATE4_STORE_FS=<fstype>` | Filesystem podman's store actually sat on for the GATE4 probe. **Required to equal `btrfs`**, for the same reason as GATE3's. |
| `GATE4_BTRFS_OK` | Podman container store on a btrfs-formatted second disk works. |
| `GATE4_FAIL` | The btrfs-store probe failed. Not part of the pass path; printed instead of `GATE4_BTRFS_OK`, same rationale as `GATE3_FAIL`. |
| `GATE5_IPTABLES_OK` | Container networking works via GATE5's first attempt (a port-published container), whatever firewall driver was in effect when it ran. **Not expected to fire** under the currently-shipped `firewall_driver = "none"` (see the netavark row in Troubleshooting) — kept in the vocabulary in case a future config change makes the first attempt viable again; `GATE5_NONE_OK` is the expected outcome today. |
| `GATE5_NONE_OK` | Container networking works with the `firewall_driver = "none"` fallback (direct container IP, no port publishing). This is the expected outcome with the config as currently shipped. |
| `GATE5_FAIL` | Neither the port-published attempt nor the none-fallback produced working networking. |
| `GATE_DONE` | `gate-guest.sh` reached the end of its run. |

Two markers were deliberately **either/or**, not single-verdict, on this
retired edition:

- **GATE2 accepts either verdict.** `GATE2_EXT4_FAIL_OK` confirms the xattr
  blocker the survey predicted; `GATE2_EXT4_UNEXPECTED_PASS` is a legitimate
  finding that would simplify the board plan. `GATE2_EXT4_FAIL_OTHER` — an
  unrelated failure — matches neither accepted pattern and therefore fails
  the gate. That is deliberate: it means the ext4-store assumption broke for
  a reason the plan did not anticipate, and that needs a human to look at it.
- **GATE5 accepts either** a port-published container working (whatever
  driver is in effect) or the `firewall_driver = "none"` fallback with a
  direct container IP. `GATE5_FAIL` means neither path produced working
  container networking. `50-x5h.conf` ships `firewall_driver = "none"`
  directly (see the netavark row in Troubleshooting for why), so GATE5's
  first attempt is not expected to succeed and `GATE5_NONE_OK` is the normal
  outcome; the first attempt is still run every time, so a regression in it
  becoming viable would show up as `GATE5_IPTABLES_OK` instead, and a
  regression in the `none` fallback itself still shows up as `GATE5_FAIL` —
  GATE5's own two-stage structure keeps probing real behavior either way,
  independent of what is shipped as the starting default. The fallback
  drop-in (`99-gate-fallback.conf`) that path writes is removed again at the
  end of GATE5 regardless of outcome, since Task 8 copies `gate-guest.sh`
  onto the board's persistent NFS root and a leftover drop-in there would
  silently shadow Task 2's `50-x5h.conf` for good; which path was taken is
  already on the record via the `GATE5_*` marker itself.

For this retired edition, `qemu-gate.exp` exited 0 only if `GATE1_LOGIN_OK`,
`GATE3_TMPFS_OK`, `GATE3_STORE_FS=tmpfs`, `GATE4_BTRFS_OK`,
`GATE4_STORE_FS=btrfs`, `GATE_DONE`, one of the GATE2 accepted markers, and
one of the GATE5 accepted markers were all present in the session log.

## Gate verdict: survey §7 answers (BSP-mimic kernel edition, retired)

The table below is the observed output of the first fully green QEMU gate run
([`30730519760`](https://github.com/youtalk/openadkit/actions/runs/30730519760),
branch `feat/autosd-x5h-rootfs`), not a restatement of what was expected.
Every row traces to a marker or a console line from that run; where a claim
is inference rather than direct observation, it says so.

The `*_STORE_FS` markers are what make findings 2-4 trustworthy, not
incidental — they prove each verdict was actually measured on the filesystem
its name claims, not on whatever `/var/lib/containers` happened to still be
mounted if an earlier `mount`/`mkfs` had silently failed. Without them this
table would be a set of assertions; with them it is a set of measurements.

| §7 question | Marker(s) observed | Observed result | Survey §7 answer |
| --- | --- | --- | --- |
| 1. Does AutoSD 10 userspace boot on a kernel with `selinux=0`? | `GATE1_LOGIN_OK`, `GATE1_SYSTEMD_STATE=degraded` | Login succeeded. `systemctl is-system-running` reported `degraded`, from exactly two failed units (`selinux-bools.service`, `ukiboot-set-success.service` — see Troubleshooting for both). | **Yes.** AutoSD 10 userspace boots and is usable on a kernel with no SELinux. `degraded` is expected and benign here, not a fault — both failing units are already named and explained in Troubleshooting so the board operator is not alarmed by seeing it. |
| 2. Does podman's default container store carry the `security.capability` xattr on ext4 without `EXT4_FS_SECURITY`? | `GATE2_STORE_FS=ext4`, `GATE2_EXT4_FAIL_OK` | Measured on ext4 (`GATE2_STORE_FS` confirms it — no mount is performed for GATE2, so this is the root export's own filesystem). `podman load` succeeded, but a follow-up `getcap` inside a running container did not find the capability. | **No** — the default container store on ext4 without `EXT4_FS_SECURITY` cannot carry `security.capability`, so it is unusable as shipped; the board needs an alternative store (findings 3-4). **This verdict was wrong once already, and the reason is worth more than the verdict itself:** the previous CI cycle reported `GATE2_EXT4_UNEXPECTED_PASS` — a false positive, because `podman load` alone exits 0 even when the xattr is silently dropped. Only after GATE2 was given the same `run` + `getcap` confirmation GATE3/GATE4 already had did this, the real answer, emerge. A load-only check is not sufficient evidence for this question on this filesystem; treat any future variant of this probe that skips the `getcap` step with the same suspicion. |
| 3. Does a tmpfs-backed container store work? | `GATE3_STORE_FS=tmpfs`, `GATE3_TMPFS_OK` | Measured on tmpfs (`GATE3_STORE_FS` confirms it, guarding against a silently-failed mount leaving the probe on the ext4 root underneath). `podman load` + `getcap` in a running container both succeeded — the capability round-trips. | **Yes.** tmpfs carries the capability xattr correctly. It is volatile — RAM-backed, gone on reboot — so it is useful as a scratch/ephemeral store, not as the board's primary persistent one. |
| 4. Does a btrfs-backed container store on a second disk work? | `GATE4_STORE_FS=btrfs`, `GATE4_BTRFS_OK` | Measured on btrfs (`GATE4_STORE_FS` confirms it — the blank second QEMU disk, `mkfs.btrfs -f` then mounted). `podman load` + `getcap` both succeeded. | **Yes**, and it is the *only* viable **persistent** option on this board: the BSP kernel has `# CONFIG_XFS_FS is not set` and `# CONFIG_F2FS_FS is not set`, and ext4 is ruled out by finding 2 above. This is exactly what makes the EPEL 10 `btrfs-progs`/`gdisk` dependency (first Troubleshooting row) non-negotiable, not a convenience choice. |
| 5. Does container networking (netavark) work without `NF_TABLES`? | `GATE5_NONE_OK` | Container networking worked with `firewall_driver = "none"`: a direct-container-IP HTTP request succeeded, which is that marker's own pass condition. (The `podman0` bridge coming up and `veth0` entering forwarding were directly observed in console output from the prior cycle, under this same, unchanged `gate-guest.sh` GATE5 logic — noted here as corroborating detail, not re-observed verbatim in this specific run's log excerpt.) | **Yes, with `firewall_driver = "none"`** — not with `"iptables"`, which is not something a future reader should retry: netavark 2.0.0 (what this image resolves) removed that backend outright, a hard config-validation rejection independent of any kernel capability (see the netavark Troubleshooting row for the version check). **Not yet confirmed, and flagged rather than assumed:** this proves networking works with `firewall_driver = "none"` on the *mimic* kernel only. The board runs the real BSP kernel with `x_tables` modules loaded from the copied module tree — a different kernel, a different module set, the same shipped config. Whether container networking also works there is what the board session still has to confirm; it is not established by this gate. **Narrower than "networking works" on its own might also suggest, independent of the mimic-vs-board-kernel caveat above:** what this gate actually proved is *host → container*, by the container's own bridge IP. `firewall_driver = "none"` means netavark installs no rules at all — not only no port-forward (already covered above, and is exactly why GATE5's first attempt fails structurally every time), but also no masquerade rule, so container → external (LAN/internet) traffic is not SNAT'd. Nothing run so far, on either kernel, exercises outbound container connectivity at all — a gap that matters beyond this branch, since the VisionPilot workloads this platform exists to host will need it. |

The gate consumed roughly 430 s of guest-visible wall clock in total, under
same-arch TCG with no `/dev/kvm` on the CI runner. But `qemu-gate.exp`'s
900 s budget is an *inactivity* timeout, not a total-runtime one, so the
number that actually validates it is the largest gap between two
consecutive markers, not the sum of all of them: in this run that gap was
112 s (`GATE4_BTRFS_OK` → `GATE5_NONE_OK`; next largest 88 s and 84 s) —
comfortably inside the 900 s budget with roughly 8x headroom, not the ~2x a
total-runtime comparison would suggest. That budget was tuned from desk
arithmetic before any gate had ever run end to end; this is the first real
timing signal for it, and it confirms the budget is sound — retiring that
open risk.

## Rebuilt kernel (6.1.102-autosd)

The BSP kernel's source is public: `renesas-rcar/linux-bsp`, branch
`v6.1.102/rcar-6.0.0.rc12`, which carries `r8a78000.dtsi` and the Ironhide
DTS variants. `kernel/build-bsp-kernel.sh <outdir>` builds it at a pinned
commit (the ref is a mutable branch, so the SHA hardcoded in the script is
the source of truth, not the branch name) with config layers merged via
`merge_config.sh`: `kernel/x5h-board.config` (the board's own
IKCONFIG-extracted base config), `kernel/autosd.config` (SELinux,
`EXT4_FS_SECURITY`, nftables, EROFS, dm-verity — each symbol commented with
the AutoSD feature needing it), `kernel/virtio.config` (QEMU-gate hardware,
deliberately compiled into the board image too), and — only under
`--firmware <dir>` — `kernel/board-firmware.config` (embeds
`rcar_gen5_mp_phy.bin`, see below). The script asserts every fragment
declaration landed, that the built `kernelrelease` is exactly
`6.1.102-autosd`, and that the compiler is exactly the pinned toolchain —
each check failing is a FATAL build error, not a warning.

The pinned toolchain is fetched and identity-asserted **before the first
`make` target**, not just before the compile, so **every mode except
`--toolchain-only` needs an x86_64 host — `--config-only` included**. That is
not a convenience: Linux 6.1's `scripts/Kconfig.include` evaluates `$(CC)` and
hard-errors when it is missing, so `olddefconfig` and `make -s kernelrelease`
both need the cross compiler to exist. The upside is that
`config-autosd.txt`'s `CONFIG_CC_VERSION_TEXT` genuinely names the compiler
that builds the `Image` in every mode. Do not "fix" a missing compiler by
installing a distro cross-gcc — that would make the emitted config depend on
whatever compiler the host happens to have, which is exactly what the pin
exists to prevent.

**The compiler is pinned to ARM GNU 13.2.Rel1 (x86_64-hosted cross), on
board evidence.** The 2026-08-05 debug session (18 boots, 14 binaries)
root-caused a boot hang to a layout-sensitive platform bug: one random
secondary CPU wedges with a corrupt PC within ~20–90 ms of SMP bringup, and
functionally identical kernels differing only in byte layout (`Image-b1a`
vs `Image-b1a1`) land on opposite sides. With the full CI config, GCC 13.2
booted 3/3 distinct layouts; GCC 13.3 wedged 3/3. The pin is **empirical,
not a guarantee** — which is why the compiler identity is asserted at
build time and again at gate runtime (`GATE1_CCVER_OK`), and why **the
board smoke remains the final arbiter for any kernel change: the QEMU gate
is structurally blind to this defect class** (no real silicon, virtio-only
I/O). ARM ships no aarch64-hosted 13.2.Rel1 toolchain, so CI cross-compiles
in a dedicated x64 job (`build-kernel`) and hands the `x5h-kernel` artifact
to the arm64 gate job.

**One build, two images.** The old "one-image" invariant (the gate boots
the byte-identical file the board netboots) could not survive the
firmware finding: the board needs an NDA blob embedded, and CI must never
see NDA material. Its replacement keeps what actually mattered — the gate
boots the same kernel *lineage* the board runs: same pinned source SHA,
same pinned toolchain, same reproducible-build env
(`KBUILD_BUILD_TIMESTAMP/USER/HOST` are fixed, so identical inputs give
byte-identical artifacts on any machine), same `kernelrelease`, same
`Image-autosd` filename; the config delta between the two images is
exactly `CONFIG_EXTRA_FIRMWARE`/`CONFIG_EXTRA_FIRMWARE_DIR`, carried by one
in-repo fragment. Kinship is checked mechanically, not by convention:
`provenance.txt` records the toolchain and artifact hashes, a local
fw-less rebuild must sha256-match the CI artifact, `GATE1_CCVER` proves
the gate booted a pinned-toolchain kernel, and `stage-rebuilt-kernel.sh`
refuses (via the exported `extract-ikconfig`) to stage any Image that does
not embed the firmware.

Artifacts (also staged into the CI debugging bundle): `Image-autosd`,
`r8a78000-ironhide-uio-autosd.dtb`, `modules-6.1.102-autosd.tar`,
`kernelrelease.txt`, `config-autosd.txt`, `provenance.txt` (toolchain
identity line, the `CONFIG_EXTRA_FIRMWARE*` values, and the sha256 of the
first three — this is what a reproducibility or "which image is this?" check
reads), and `extract-ikconfig` (the pinned tree's own script, exported so a
staging host can read an `Image`'s embedded config with no kernel checkout;
`stage-rebuilt-kernel.sh` uses it to refuse firmware-less images).

`modules-6.1.102-autosd.tar` deliberately carries **no** depmod-generated
index files (`modules.dep`, `modules.dep.bin`, `modules.alias`,
`modules.alias.bin`, `modules.symbols`, `modules.symbols.bin`,
`modules.softdep`, `modules.devname`, `modules.builtin.bin`,
`modules.builtin.alias.bin`): `modules_install` builds them with the
*building* machine's `depmod`, so their bytes track the host's kmod version
rather than the kernel and would defeat byte-identity across machines. Both
consumers regenerate them with `depmod -b <root> 6.1.102-autosd` right after
extracting, and both then assert `modules.dep` exists — anything else that
extracts this tar must do the same, or `modprobe` in the target will fail.
The build-generated `modules.order`, `modules.builtin` and
`modules.builtin.modinfo` **are** included: `depmod` reads them.

**The firmware split.** The board's own kernel bakes in three Renesas
blobs; they ship only in the NDA R-Car xOS SDK, so no from-source CI build
can embed them. The gate image therefore carries
`CONFIG_EXTRA_FIRMWARE=""` — but the 2026-08-05 board session proved this
is **not** a difference without consequence: without `rcar_gen5_mp_phy.bin`
the built-in MP-PHY driver fails probe, `renesas_eth_sw` defers forever,
and the board has no TSN link and cannot NFS-netboot at all (the state
commit 695106c unknowingly shipped). The board image is built locally with
`--firmware <dir>` (a directory containing the SDK blob), which merges
`kernel/board-firmware.config` to embed exactly that one blob. The two
PCIe6 blobs (`rcar_gen5_pcie6_iccm.bin`, `rcar_gen5_pcie6_dccm.bin`) stay
excluded from both images: nothing is attached to PCIe6 on this board, and
the BSP kernel loads them only to report `Phy link never came up`. **NDA
boundary:** the blobs, and any Image embedding them, exist only on the dev
machine and the board LAN — never in the repo, CI, CI logs, or CI
artifacts; the repo carries only the blob filename, which the public
linux-bsp driver source already does.

### Gate markers (rebuilt-kernel edition)

This is the marker vocabulary `gate-guest.sh` and `qemu-gate.exp` actually
implement today — see "Gate markers (BSP-mimic edition, retired)" above for
the vocabulary this replaced. Gate numbers are stable identifiers, not a
sequence: GATE5 (the retired `firewall_driver = "none"` path) is not
reused — GATE6 and GATE7 are new, not GATE5's successor under a new name.

| Marker | Meaning | Required |
| --- | --- | --- |
| `GATE1_LOGIN_OK` | Guest login succeeded. | yes |
| `GATE1_KVER=<release>` | `uname -r` inside the guest. The runtime `kernelrelease` half of the one-build-two-images invariant (`GATE1_CCVER_OK` is the toolchain half) — `build-bsp-kernel.sh` asserts `kernelrelease` is exactly `6.1.102-autosd` at build time, but this is what proves the gate actually *booted* that release, the same one the board netboots. | yes, must equal `6.1.102-autosd` |
| `GATE1_CCVER=<...>` | `/proc/version` of the booted kernel — records which compiler built it. | informational |
| `GATE1_CCVER_OK` | `/proc/version` contains `Arm GNU Toolchain 13.2.rel1`: the gate booted a pinned-toolchain kernel. The wedge itself is invisible to QEMU, so this is the one pin-regression CI can catch. | yes |
| `GATE1_CCVER_FAIL` | The booted kernel was built by some other compiler — the toolchain pin has been broken. | must be ABSENT |
| `GATE1_SYSTEMD_STATE=<state>` | `systemctl is-system-running` output, informational — no expected value is asserted here; unlike the retired edition, no CI or board run of this gate has recorded one yet. | no |
| `GATE1_MODPROBE_FAIL` | `modprobe -a overlay veth bridge br_netfilter btrfs nf_tables` failed against the injected/staged module tree — a staging bug, not a kernel one (the rebuilt kernel ships these as modules, exactly as the BSP kernel does). | must be ABSENT |
| `GATE2_STORE_FS=<fstype>` | Filesystem podman's store sat on for the GATE2 probe (expected `ext4`, since GATE2 mounts nothing). | yes, must equal `ext4` |
| `GATE2_EXT4_OK` | The ext4 store holds the `security.capability` xattr — `EXT4_FS_SECURITY=y` is the point of the rebuild. Confirmed by `podman load` **and** a follow-up `getcap` inside a running container, not just a `load` that happened to exit 0 (the cycle-5/6 lesson from the retired edition, carried forward so this cannot silently false-pass). | yes |
| `GATE2_EXT4_FAIL` | The ext4-store xattr probe failed (load error, or `load` succeeded but `getcap` came up empty). Not part of the pass path. | no |
| `GATE3_STORE_FS=<fstype>` | Filesystem podman's store sat on for the GATE3 probe. **Required to equal `tmpfs`** — otherwise a silently-failed tmpfs mount could fall through to the ext4 root underneath and still print `GATE3_TMPFS_OK` for the wrong reason. | yes, must equal `tmpfs` |
| `GATE3_TMPFS_OK` | Podman container store on tmpfs works, including the capability xattr round-trip. Unchanged from the retired edition. | yes |
| `GATE3_FAIL` | The tmpfs-store probe failed. Not part of the pass path. | no |
| `GATE4_STORE_FS=<fstype>` | Filesystem podman's store sat on for the GATE4 probe. **Required to equal `btrfs`**, same reason as GATE3's. | yes, must equal `btrfs` |
| `GATE4_BTRFS_OK` | Podman container store on a btrfs-formatted second disk works. Unchanged from the retired edition. | yes |
| `GATE4_FAIL` | The btrfs-store probe failed. Not part of the pass path. | no |
| `GATE6_NFT_PORT_OK` | netavark's nftables driver (`config/60-nftables.conf`, staged only alongside this kernel — see "Board deployment" below) publishes a container port. Polled: 30 iterations of `curl --max-time 5` + `sleep 2`. `GATE5_IPTABLES_OK`'s replacement for this kernel, now the expected outcome rather than an unlikely one. | yes |
| `GATE6_NFT_PORT_FAIL` | The published-port probe failed after the full poll. On this kernel that is a real regression, not the structural no-op it was under the retired `firewall_driver = "none"` path. | no |
| `GATE6_SNAT_OK` | Container→external is masqueraded: a fresh busybox container's `wget -T 10` reaches the slirp-mapped host listener at `10.0.2.2:8099`. Polled: 5 iterations of `podman run … wget -T 10` + `sleep 2` — the `-T 10` bounds each attempt so a missing masquerade rule (SYN black-holed) fails fast instead of eating the kernel's syn-retry ceiling. This is the first gate to exercise outbound container connectivity at all, closing the honest-networking gap the retired edition's survey answer 5 flagged. | yes |
| `GATE6_SNAT_FAIL` | The outbound-SNAT probe failed after the full poll. | no |
| `GATE7_SELINUX_PERMISSIVE_OK` | `/sys/fs/selinux/enforce` reads `0` — SELinux is compiled in and permissive (`enforcing=0` on the cmdline). Read directly from selinuxfs rather than via `getenforce`, so the marker cannot depend on which utility package made it into the image. | yes |
| `GATE7_SELINUX_ENFORCE=<n>` | selinuxfs is present but `enforce` is not `0` — SELinux is enforcing when the cmdline asked for permissive. | no |
| `GATE7_SELINUX_ABSENT` | No `/sys/fs/selinux/enforce` at all — SELinux isn't compiled into this boot. | no |
| `GATE7_SELINUX_BOOLS_OK` | `selinux-bools.service` did not fail. It failed under the BSP/retired-mimic kernel's absent SELinux (see the Troubleshooting row) — with SELinux present it must now come up clean. | yes |
| `GATE7_SELINUX_BOOLS_FAILED` | `selinux-bools.service` failed even with SELinux present — a real regression, not the benign BSP-kernel failure the Troubleshooting row documents. | no |
| `GATE7_SELINUX_BOOLS_ABSENT` | `selinux-bools.service`'s `LoadState` reads `not-found` — the unit is missing from this image entirely. Disambiguates from `GATE7_SELINUX_BOOLS_OK`: `systemctl is-failed` alone exits nonzero both for "healthy" and for "does not exist", so without this check a dropped unit could otherwise print `_OK`. | no |
| `GATE_RPMSG_ETH_UNIT_PASS` | GATE8: the `rpmsg-eth` TAP bridge daemon's own unit test (`rpmsg-eth/test-rpmsg-eth.sh`) passed inside its dedicated Fedora test container — real tap0 on the guest kernel under test, a mock endpoint (socat pty), `--network=none`. Requires both a zero `podman run` exit status and a literal `TEST_PASS` in its output (see `gate-guest.sh`'s GATE8 comment for why exit-status-alone is not sufficient). | yes |
| `GATE_RPMSG_ETH_UNIT_FAIL` | The `rpmsg-eth` unit test failed — either the container/build step itself failed, or `test-rpmsg-eth.sh` ran and reported a `TEST_FAIL`. Not part of the pass path. | no |
| `GATE_DONE` | `gate-guest.sh` reached the end of its run. | yes |

`qemu-gate.exp` exits 0 only if every "Required: yes" marker above is present
in the session log (with the fstype-qualified ones matching exactly, e.g.
`GATE2_STORE_FS=ext4`) and every "Required: must be ABSENT" marker
(`GATE1_MODPROBE_FAIL`, `GATE1_CCVER_FAIL`) is absent from it.

### Board deployment

Deployment is two steps: build the board's own kernel bundle, then stage it
onto the NFS root and TFTP directory with
`scripts/stage-rebuilt-kernel.sh <staged-nfs-root> <kernel-bundle-dir> <tftp-dir>`.

`<kernel-bundle-dir>` must come from a **`--firmware` build**. The CI
artifact is the firmware-less *gate* image and cannot NFS-netboot at all (see
"The firmware split" above), so build the board bundle locally first, from a
directory holding the SDK blob — never in CI, never committed:

```
kernel/build-bsp-kernel.sh --firmware <blob-dir> <kernel-bundle-dir>
```

That is enforced, not merely expected: `stage-rebuilt-kernel.sh`
`extract-ikconfig`s the candidate `Image-autosd` and **FATALs before anything
reaches TFTP** unless the embedded config carries
`CONFIG_EXTRA_FIRMWARE="rcar_gen5_mp_phy.bin"`. Handing it the CI artifact —
or a local build where `--firmware` was omitted — fails there and costs a
full 30–60 minute rebuild mid session, so confirm the bundle's
`provenance.txt` names the blob before starting. (`build-bsp-kernel.sh`
itself FATALs if `--firmware` is written *after* `<outdir>` instead of
before it, so that particular mistake never reaches this guard. A second,
separate FATAL here covers an `Image` from which no embedded config can be
read at all — truncated or corrupt. That one is *not* the `--firmware`
question and rebuilding with `--firmware` will not fix it.)

With that bundle in hand, and after Board bring-up's step 1
(`stage-nfs-rootfs.sh`, below) has staged the NFS root, add the rebuilt
kernel on top of it — strictly additive, no BSP file touched — as root on the
NFS server host:

```
scripts/stage-rebuilt-kernel.sh <staged-nfs-root> <kernel-bundle-dir> <tftp-dir>
```

This installs `Image-autosd` and `r8a78000-ironhide-uio-autosd.dtb` into
`<tftp-dir>`, extracts and `depmod`s the module tree into `<staged-nfs-root>`,
stages `config/60-nftables.conf` into
`<staged-nfs-root>/etc/containers/containers.conf.d/`, and refreshes
`<staged-nfs-root>/var/lib/autosd-test/board-podman-smoke.sh` from this
branch's copy — after this, both kernels boot the same NFS root (Board
bring-up, step 2, is the U-Boot side of the selection). The refresh matters
because `stage-nfs-rootfs.sh` (Board bring-up, step 1) only ever copies
`board-podman-smoke.sh` once, at initial staging, and refuses to re-run over
an already-staged root — a board session reusing a root staged before this
branch would otherwise run the old script (no `ext4loop` mode, no
rebuilt-kernel detection) and silently prove far less than it looks like it
does. Safe to overwrite: the refreshed script auto-detects BSP vs. rebuilt
via `uname -r`, so its behaviour on a rollback boot is unchanged.

Kernel selection is three U-Boot variables (`uboot/autosd-boot.env`'s header
carries the full BSP/rebuilt value table); the script prints the exact
`setenv` lines for both directions at the end of a successful run:

```
U-Boot (rebuilt): setenv kernel_file Image-autosd ; setenv dtb_file r8a78000-ironhide-uio-autosd.dtb ; setenv selinux_arg enforcing=0
U-Boot (rollback): setenv kernel_file Image ; setenv dtb_file <bsp-dtb> ; setenv selinux_arg selinux=0
  NOTE: selinux_arg expands at 'setenv bootargs_autosd' time, not at 'run' time -- after setenv'ing it, re-enter the bootargs_autosd line from uboot/autosd-boot.env before 'run bootcmd_autosd', or the old value stays baked in.
```

Rollback is **not** just those three variables set back to the BSP values.
`stage-rebuilt-kernel.sh` also staged `60-nftables.conf` onto the shared NFS
root, and the BSP kernel has no `CONFIG_NF_TABLES` — a U-Boot-only rollback
would leave the BSP kernel booting with a firewall driver it cannot run.
Complete rollback needs the drop-in removed too, exactly as the script
prints it:

```
Rollback ALSO needs: rm -f <staged-nfs-root>/etc/containers/containers.conf.d/60-nftables.conf
  (the drop-in selects the nftables driver, which the BSP kernel cannot run -- both kernels share this NFS root)
```

Fallback chain if the rebuilt kernel misbehaves, weakest change first:
`enforcing=0` (default, permissive) → `selinux_arg=selinux=0` (SELinux out
of the equation entirely, still the rebuilt kernel and nftables) → the full
rollback above (BSP kernel, BSP U-Boot values, drop-in removed). The middle
rung is not just `setenv selinux_arg selinux=0`: `selinux_arg` expands at
`setenv bootargs_autosd` time (see `uboot/autosd-boot.env`'s header), so
that variable alone changes nothing already baked into `bootargs_autosd` —
re-enter the `setenv bootargs_autosd "..."` line with the new value before
`run bootcmd_autosd`, or the boot proceeds with the old, already-expanded
value and no error.

Smoke order on the rebuilt kernel (Board bring-up, step 3): `tmpfs` →
`ext4loop` (a zero-mutation `EXT4_FS_SECURITY` proof on a `/run`-backed loop
file — no persistent device is touched) → `btrfs <dev>` (same
tmpfs-must-pass-first interlock as before, unaffected by `ext4loop`'s
addition). `ext4loop` is expected to **fail** on the image as it currently
ships, with `SMOKE_ext4loop_MKFS_FAIL`: it needs `mkfs.ext4` and the aib
manifest installs no `e2fsprogs` (see Board bring-up step 3). The interlock
only gates `btrfs` on `tmpfs`, so that failure does not block the rest of
the sequence. Before running the smoke sequence, start the outbound-SNAT
listener on the host PC: `python3 -m http.server 8099 --bind 192.168.0.1` —
`board-podman-smoke.sh`'s `SMOKE_EXT_URL` env var overrides the target if
the site's addressing differs, and `SMOKE_EXT_URL=skip` skips the probe
entirely instead of failing it.

GATE7 proves SELinux loads and is permissive on an **ext4** root, where
every file carries the `security.selinux` xattr baked in by the image. The
board's root is **NFSv3, which carries no xattrs at all** — every object
gets a single `genfscon` context instead. Permissive mode means it still
works either way, but the labelling state the board actually runs under is
not the one GATE7 measured: the gate proves SELinux loads and is
permissive, not that the board's per-file labelling is correct. This
matters at the console, not just in principle — permissive-mode AVC
denials print at `KERN_WARNING`, and enough of them can make a slow serial
console unusable. Run `dmesg -n 1` right after logging in on the rebuilt
kernel to keep denial spam off the console before it becomes a problem.
`selinux_arg=selinux=0` (see the re-`setenv bootargs_autosd` caveat above)
is the escape hatch if AVC output floods it anyway.

### Survey §7 addendum

With the rebuilt kernel, the networking rows the retired edition could only
flag as open gaps are now answered honestly: published ports and
container→external SNAT are exercised by GATE6 (and on the board by
`SMOKE_*_NET_PORT_*`/`SMOKE_*_SNAT_*`), closing the final-review I5 gap
recorded in the retired edition's survey answer 5. ext4 becomes a viable
container store (GATE2/`GATE2_EXT4_OK`, answer 2's finding reversed), so
btrfs is now a choice for the board's persistent store rather than the only
option ext4's `EXT4_FS_SECURITY` gap left.

## Running locally

The same gate CI ran replays on an x86 dev host. Two reasons this is worth
doing beyond interactive debugging: it is the only place the tar → ext4
reassembly gets exercised outside CI, and that reassembly is exactly what
`scripts/stage-nfs-rootfs.sh` does for the board's NFS root (`tar --xattrs
--xattrs-include='*.*' -xf <tarball> -C <dest-dir>`) — so a green local
replay is corroborating evidence for the board staging path, not just a
debugging convenience. It also leaves a local copy of `x5h-rootfs.tar` on
disk, which is what `stage-nfs-rootfs.sh` consumes at board time.

The replay needs three inputs: the rootfs tar, the rebuilt kernel's output
directory (`Image-autosd`, `modules-6.1.102-autosd.tar` and
`kernelrelease.txt` all come from it), and the three test-image tars. Build
them from source (below) or download a bundle CI already produced. **Neither
route needs the NDA R-Car xOS SDK or any credential-gated download** — the
rootfs resolves from public AutoSD 10 and EPEL 10 repos, the kernel builds
from the public `renesas-rcar/linux-bsp` git source at the SHA pinned in
`kernel/build-bsp-kernel.sh`, and the test images come from `public.ecr.aws`
and `quay.io`. The two NDA-gated inputs this platform does have —
`<bsp-rootfs-dir>` under "Board bring-up" below, and the `--firmware <dir>`
blob that only the board image embeds — sit outside the replay, which
touches neither.

### Building the inputs from source

The durable route: it depends on nothing that expires. Each command below is
the one CI runs, in CI's order.

```bash
cd platforms/autosd/x5h

# 1. The AutoSD rootfs tar. `--tar` builds the container content straight
#    into a tar, so there is no `podman create` + `podman export` round trip
#    here and no root-vs-user podman store question either. The current aib
#    CLI is bootc-shaped — no `--mode`, no `--export`, no `list-exports` —
#    so do not reach for the invocation in ../README.md's General
#    Instructions; it is for planning-simulator and does not apply here.
curl -fL -o auto-image-builder.sh \
  "https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/raw/main/auto-image-builder.sh?ref_type=heads"
chmod +x auto-image-builder.sh
sudo bash ./auto-image-builder.sh build-builder --distro autosd10-sig
sudo bash ./auto-image-builder.sh build --tar \
  --distro autosd10-sig --target qemu \
  --define-file aib/vars.yml \
  aib/x5h-rootfs.aib.yml aib/x5h-rootfs.tar

# 2. The rebuilt BSP kernel bundle. build-bsp-kernel.sh checks out
#    renesas-rcar/linux-bsp at the SHA pinned in the script, merges
#    kernel/x5h-board.config, kernel/autosd.config and kernel/virtio.config
#    with merge_config.sh, and then *asserts* — fatally, not as warnings —
#    that every fragment declaration landed, that `kernelrelease` is
#    exactly 6.1.102-autosd, and that the compiler is the pinned ARM GNU
#    13.2.Rel1 toolchain it fetched itself. Deliberately no `--firmware`
#    here: that mode embeds the NDA blob and belongs to the board image
#    only (see "Board deployment" above), never to the gate.
kernel/build-bsp-kernel.sh /tmp/x5h-kernel

# 3. The three test images. make-test-images.sh also verifies the captest
#    archive really carries a security.capability PAX record, so an xattr
#    silently dropped at build time cannot reach the gate disguised as a
#    GATE2 finding. The third, rpmsg-eth-docker.tar, carries the daemon
#    source and its pty-mock unit test for GATE8 to run in-guest.
scripts/make-test-images.sh /tmp/x5h-testimages
```

Three things to know before running these, because CI runs no single host
through all of them — the kernel builds in an x64 `build-kernel` job and
everything else on native arm64 (`ubicloud-standard-16-arm`):

- **Step 2 requires an x86_64 host, and brings its own compiler.** ARM ships
  no aarch64-hosted 13.2.Rel1 toolchain, so `build-bsp-kernel.sh`
  cross-compiles from x86_64 in every mode except `--toolchain-only` —
  `--config-only` included, because Linux 6.1's `scripts/Kconfig.include`
  evaluates `$(CC)` even for config targets. Do **not** work around a
  missing compiler by installing a distro `gcc-aarch64-linux-gnu`: the pin
  is empirical (13.2 booted 3/3 layouts, 13.3 wedged 3/3 — see "Rebuilt
  kernel" above) and substituting whatever compiler the host happens to
  have is exactly the path by which the SMP-bringup wedge returns.
- **Steps 1 and 3 emit aarch64 containers.** On an x86_64 host they need
  `qemu-user-static` binfmt registered (`sudo apt install qemu-user-static
  binfmt-support`, or `docker run --privileged --rm tonistiigi/binfmt
  --install arm64`). CI runs them natively on arm64 instead.
- **Budget generously, but don't trust a figure.** There is no verified
  end-to-end number for this rebuilt-kernel edition: the ~25 minute figure
  the retired BSP-mimic edition recorded predates both the kernel rebuild
  and the x64/arm64 job split, and on an x86 host the aib and container
  builds run under binfmt besides. Budget accordingly rather than planning
  against a number nobody has measured for this pipeline.

`AIB_PODMAN_OPTIONS="-v /run/containers:/run/containers"`, which CI passes to
both `auto-image-builder.sh` invocations, is a workaround for that runner's
bind-mounted container storage and is not needed on an ordinary host.

### Downloading a CI bundle instead

A shortcut, not a substitute: **artifacts expire after 14 days**, and every
bundle this branch has produced is already past that, so expect this to fail
and fall back to building unless a run finished within the last two weeks.
The run ID still resolves after its artifact is gone, so the failure surfaces
at `gh run download`, not at the lookup.

```bash
gh run download --repo youtalk/openadkit -n x5h-gate-bundle -D /tmp/x5h-bundle \
  "$(gh run list --repo youtalk/openadkit --workflow autosd-x5h-rootfs.yaml \
       --branch feat/autosd-x5h-kernel --status success --limit 1 \
       --json databaseId --jq '.[0].databaseId')"

# The workflow stages a flat bundle before upload — one `testimages/`
# subdirectory, everything else at the top level:
#   Image-autosd  r8a78000-ironhide-uio-autosd.dtb  modules-6.1.102-autosd.tar
#   kernelrelease.txt  config-autosd.txt  x5h-rootfs.tar  x5h-gate.log
#   testimages/busybox-oci.tar  testimages/captest-docker.tar
#   testimages/rpmsg-eth-docker.tar
# There is no ext4 export in it: it is reproducible and large, so the replay
# rebuilds it from the tar, the same way the CI workflow's own "Derive the
# ext4 export from the tar" step does.
find /tmp/x5h-bundle -type f
```

### Replaying the gate

Host tools: `qemu-system-aarch64` and `qemu-img` (Debian/Ubuntu: packages
`qemu-system-arm` and `qemu-utils` — `qemu-img` is what `run-qemu-gate.sh`
shells out to when `/tmp/x5h-blank.img` doesn't already exist, so it's a
runtime dependency of this replay, not a build-only one), `expect` (the
`qemu-gate.exp` interpreter), `e2fsprogs` for `mkfs.ext4`, and `python3`
for the SNAT listener step 3 starts; plus `gh` (authenticated) if you took
the download route. The arm64 `build-and-gate`
job's "Install host tools" step installs exactly `podman`, `skopeo`,
`qemu-system-arm`, `qemu-utils` and `expect` — nothing else, because the
kernel compile no longer happens there: `flex`, `bison`, `libssl-dev`,
`libelf-dev`, `bc` and `xz-utils` moved to the x64 `build-kernel` job along
with it. `e2fsprogs` and `gh` are in neither list because the runners ship
both preinstalled. None of the kernel-build packages are needed here: this
replay consumes a kernel bundle that "Building the inputs" above produced,
or one it downloads pre-built.

First point these four variables at whichever route you took. They are the only
difference between the two:

```bash
cd platforms/autosd/x5h   # the relative paths below, and ./scripts/... later, need this

# Built from source:
TAR=aib/x5h-rootfs.tar
KERNELDIR=/tmp/x5h-kernel
KERNEL="$KERNELDIR/Image-autosd"
TESTIMAGES=/tmp/x5h-testimages

# ...or from a downloaded bundle. `find` rather than fixed paths, because
# the lookups have to be depth-agnostic — and note TESTIMAGES resolves to
# the bundle's `testimages/` subdirectory, while KERNELDIR is the bundle
# root, which is where kernelrelease.txt and the module tar sit.
TAR="$(find /tmp/x5h-bundle -name x5h-rootfs.tar)"
KERNEL="$(find /tmp/x5h-bundle -name Image-autosd)"
KERNELDIR="$(dirname "$KERNEL")"
TESTIMAGES="$(dirname "$(find /tmp/x5h-bundle -name busybox-oci.tar)")"
```

Everything to this point runs as your own user. Loop-mounting the ext4 export
(step 1's `mount`/`tar`/`umount`) and running `qemu-gate.exp` (step 4) need
root, so those commands are prefixed `sudo`. Step 2's
`inject-test-images.sh` also needs root for its own loop mount, but sudoes
internally rather than needing its own invocation prefixed — its `sudo
mount`/`sudo cp`/`sudo umount` calls are what require root, not
`./scripts/inject-test-images.sh` itself.

```bash
# 1. Build the ext4 export from the tar. truncate/mkfs need no privilege
#    (they operate on a plain file); the loop mount does.
truncate -s 6G /tmp/x5h-replay.ext4
mkfs.ext4 -q /tmp/x5h-replay.ext4
mnt="$(mktemp -d)"
sudo mount -o loop /tmp/x5h-replay.ext4 "$mnt"
# --xattrs: mirrors the CI step exactly. A plain `tar xf` silently drops
# extended attributes on extract (exit 0, no warning) even when the
# archive carries them, so security.capability on e.g. ping would
# otherwise vanish here regardless of kernel. The rebuilt kernel this
# export boots under has EXT4_FS_SECURITY=y, so GATE2 now asserts the
# restored capability survives rather than that it fails on a
# constrained kernel — but either way, without --xattrs the export
# itself would never have carried the capability to test in the first
# place.
sudo tar --xattrs --xattrs-include='*.*' -xf "$TAR" -C "$mnt"
sudo umount "$mnt"
rmdir "$mnt"

# 2. Inject the test payload. Use the script, not a hand-copy: besides the
#    three test tars and gate-guest.sh, it also neutralizes /etc/fstab
#    (preserving the original as fstab.image) — skip that and the guest
#    reboot-loops on the stock fstab's ESP entry (see Troubleshooting) —
#    and now also extracts the rebuilt kernel's module tree from its third
#    argument (depmod'ing it for the guest) and installs the in-tree
#    `config/60-nftables.conf` drop-in, required by GATE1's modprobe
#    prelude and GATE6's nftables driver respectively.
./scripts/inject-test-images.sh /tmp/x5h-replay.ext4 "$TESTIMAGES" "$KERNELDIR"

# 3. Start the host listener GATE6_SNAT_OK probes. The guest reaches it as
#    http://10.0.2.2:8099/, which slirp maps onto the host's
#    127.0.0.1:8099. The CI workflow runs this listener itself, so it is
#    easy to miss here — and GATE6_SNAT_OK is a *required* marker, so a
#    replay without it fails the gate with GATE6_SNAT_FAIL for a reason
#    that has nothing to do with the kernel under test. Bind to loopback,
#    not 0.0.0.0: slirp only ever needs 127.0.0.1, and this serves the
#    current directory to whoever can reach it.
python3 -m http.server 8099 --bind 127.0.0.1 >/dev/null 2>&1 &
listener=$!

# 4. Run the gate. /tmp/x5h-blank.img is deliberately not pre-created here:
#    run-qemu-gate.sh makes it itself (`qemu-img create -f raw ... 8G`) when
#    the path doesn't exist yet, the same fallback CI relies on rather than
#    pre-creating it — which is why qemu-img (qemu-utils) is a listed
#    prerequisite above, not an optional one.
#    On an x86 host, run-qemu-gate.sh's aarch64+/dev/kvm check is always
#    false, so this is cross-arch TCG — materially slower than CI's
#    same-arch TCG. There is no verified guest-time figure yet for this
#    rebuilt-kernel edition (that lands with the first green CI run on
#    this branch); the ~430 s figure in "Gate verdict" above is from the
#    retired BSP-mimic edition and is not a reliable stand-in for it — a
#    from-source kernel doing real module loading and SELinux policy load
#    is not expected to match that number either way. Budget accordingly
#    rather than trusting a specific figure. qemu-gate.exp's inactivity
#    timeout re-arms on every marker, so a slow-but-progressing run will
#    not be killed early.
sudo ./scripts/qemu-gate.exp ./scripts/run-qemu-gate.sh \
  "$KERNEL" /tmp/x5h-replay.ext4 \
  /tmp/x5h-blank.img /tmp/x5h-local-gate.log

# 5. Stop the listener — it outlives the gate otherwise.
kill "$listener"

# 6. Read the result the same way CI's "Show gate markers" step does.
grep -E 'GATE[0-9_]+' /tmp/x5h-local-gate.log
```

`qemu-gate.exp` itself exits 0 only once every required marker from the
"Gate markers (rebuilt-kernel edition)" table (in "Rebuilt kernel
(6.1.102-autosd)" above) is present in the log, and `GATE1_MODPROBE_FAIL`
and `GATE1_CCVER_FAIL` are both absent — check `echo $?` after it returns,
or just compare the `grep`
output above against that table for the expected line-for-line match.

## Board bring-up

Board time is scarce and one-shot — no rerun scheduled. The order below encodes the plan's
board-safety invariants; do not reorder it.

### 1. Stage the AutoSD NFS root

The two inputs come from wherever "Running locally" above got them — built from source, or
unpacked from a CI bundle. The bundle is flat but not entirely flat: the tarball sits at the
top level while the three test images sit one level down, under `testimages/`. Resolve both by
lookup rather than by assuming a fixed path:

```bash
TAR="$(find /tmp/x5h-bundle -name x5h-rootfs.tar)"
TESTIMAGES="$(dirname "$(find /tmp/x5h-bundle -name busybox-oci.tar)")"
```

Built from source instead, those two are `aib/x5h-rootfs.tar` and whatever output directory
was passed to `scripts/make-test-images.sh`.

Then, as root on the NFS server host:

```bash
scripts/stage-nfs-rootfs.sh "$TAR" <bsp-rootfs-dir> <dest-dir> "$TESTIMAGES"
```

`<bsp-rootfs-dir>` is the existing BSP NFS root — it is only ever read from (to copy
`/lib/modules/6.1.102-yocto-standard`, since overlayfs/veth/bridge/x_tables are all `=m` on
the BSP kernel), never modified. `<testimages-dir>` is the directory that *directly* contains
`busybox-oci.tar` and `captest-docker.tar` — **with a CI bundle that is the bundle's
`testimages/` subdirectory, not the bundle root.** The script verifies both tars are present
before it creates anything, so passing the bundle root fails immediately with a diagnostic
instead of part-way through staging, with `<dest-dir>` already populated and unstamped.

The script refuses to run if `<dest-dir>` already exists, and prints `OK: staged at
<dest-dir>` plus a `<dest-dir>/.x5h-stage-complete` stamp file on success. If a previous run
was interrupted, `<dest-dir>` can exist without that stamp — treat that as incomplete, not
resumable: `rm -rf <dest-dir>` and rerun the script from scratch. Once staged, add the new
export to `/etc/exports` (mirror the existing BSP export line's options) and run
`exportfs -ra`.

### 2. U-Boot: `printenv` backup, then `bootcmd_autosd`

Before touching the U-Boot environment, capture a full `printenv` to the session log — this
is what makes the next step reversible. The default `bootcmd` is **never** modified; only a
new `bootcmd_autosd` variable is added, from the `uboot/autosd-boot.env` template.

The template's `${...}` placeholders are of three kinds. `serverip` is already defined by
this board's U-Boot environment. `kernel_addr_r` and `fdt_addr_r` **may not be** — this
board's own default `bootcmd` loads to literal addresses rather than through those
variables, and an undefined `${kernel_addr_r}` expands to nothing, silently demoting
`tftp ${kernel_addr_r} ${kernel_file}` to a load at `${loadaddr}`: a wrong-address load that
still looks like a working command. Run `printenv kernel_addr_r fdt_addr_r` first and, if
either is "not defined", `setenv` it to the matching literal address read out of the
`printenv` backup taken at the start of the session (never a guessed address). The rest —
six variables, all `setenv` at the prompt **before the first line of the template**, not
merely before `bootargs_autosd` — split into two groups: `autosd_export_path`,
`bootargs_bsp`, and `board_ip_config` are genuinely site values, operator-supplied from
`x5h-work/HANDOFF.md` (not committed to this repo); `dtb_file`, `kernel_file`, and
`selinux_arg` select which kernel boots and take one of exactly two documented value pairs —
BSP or rebuilt, see `uboot/autosd-boot.env`'s header for the full table, or "Rebuilt kernel
(6.1.102-autosd)" above for the rebuilt pair specifically. `autosd_export_path` is consumed
by the *first* line (`autosd_nfsroot`), which is unquoted and therefore expands immediately,
exactly like the double-quoted `bootargs_autosd` line that follows it. Setting
`autosd_export_path` only after `autosd_nfsroot` has already run still bakes an empty export
path into it (`nfsroot=<ip>:,nfsvers=3`), and that string is plausible enough to pass a
casual glance. After entering all three lines, read back `printenv autosd_nfsroot
bootargs_autosd` and check that the export path and the `ip=` config are actually present in
the output — not just that the strings "look complete".

The board's saved U-Boot environment may already hold a `bootcmd_autosd` from a previous
session, with the kernel filename hardcoded instead of `${kernel_file}` — `setenv` replaces a
variable outright, but only when re-entered, so skipping straight to `run bootcmd_autosd` on a
board that already has one saved runs *that* stale command, hardcoded filename and all,
ignoring whatever `kernel_file`/`dtb_file`/`selinux_arg` were just `setenv`'d. Always re-enter
all three `setenv` lines above first. Then read back `printenv bootcmd_autosd` — not
`bootargs_autosd`, which a stale `bootcmd_autosd` can still produce a plausible-looking value
for — and confirm `${kernel_file}` appears **unexpanded** in the output. Only then boot the
AutoSD NFS root with:

```
run bootcmd_autosd
```

The template chains `bootcmd_autosd`'s four commands with `&&`, not `;`. That is a hard
requirement of how these lines reach the board, not a style choice: the console sender types
through tmux `send-keys -l`, whose argument parser swallows a bare `;` as its own command
separator, so a semicolon never arrives. `&&` also matches this board's default `bootcmd`
and stops the chain on a failed `tftp` instead of `booti`-ing whatever was already at that
address. For the same reason the `nfsroot=` options are just `nfsvers=3` — the exact option
string the BSP netboot is proven to mount with on this hardware (`proto=tcp` is already the
kernel default here, as `findmnt` on the running BSP shows).

Once logged in on the **BSP kernel**, `systemctl is-system-running` reporting `degraded` is
expected, not a fault — the retired BSP-mimic QEMU gate reproduced the identical state from
exactly two known-benign failed units (`selinux-bools.service`: no SELinux in this kernel;
`ukiboot-set-success.service`: no ukibootctl partition, since this image ships
`use_efipart: false` — see the Troubleshooting table below for both). Neither should be
chased as a live problem. Booting the **rebuilt kernel** instead is different: SELinux is
compiled in and `enforcing=0` by default, so `selinux-bools.service` must now come up clean
— a failed `selinux-bools.service` there is `GATE7_SELINUX_BOOLS_FAILED`'s live equivalent,
a real regression, not the benign BSP-kernel finding above (see "Gate markers
(rebuilt-kernel edition)" in "Rebuilt kernel (6.1.102-autosd)" above).

At the end of the session, re-verify the unmodified BSP boot path still works (power cycle,
default `bootcmd`, BSP NFS root) before releasing the board.

### 3. On-board podman smoke: tmpfs before btrfs

`scripts/board-podman-smoke.sh` is staged onto the NFS root under `/var/lib/autosd-test/`
by step 1 — **not** on `PATH`, so invoke it by absolute path (a `command not found` at a
1.8 Mbps serial prompt costs real time). Phase order is an enforced invariant, not just a
documented one: `btrfs` refuses to run unless a `tmpfs` run has already passed on this boot.
On the BSP kernel there are two phases (`tmpfs`, `btrfs`); on the **rebuilt kernel** a third,
`ext4loop` (also zero board mutation — a `/run`-backed loop file, not a real device), runs
between them — see "Rebuilt kernel (6.1.102-autosd)" above for the full three-phase sequence
and the outbound-SNAT listener it needs. **`ext4loop` cannot pass on the image as shipped**:
it calls `mkfs.ext4`, and `aib/x5h-rootfs.aib.yml` installs no `e2fsprogs`, so the phase ends
in `SMOKE_ext4loop_MKFS_FAIL`. That is a packaging gap, not a kernel finding — the rebuilt
kernel's `EXT4_FS_SECURITY` is already proven by GATE2 — and closing it needs a rootfs rebuild,
which is deliberately out of scope here. Expect that one red marker in a board session and
carry on to `btrfs`. The walkthrough below
covers the `tmpfs`/`btrfs` pair common to both kernels; invoke `ext4loop` the same way, with
no extra argument, between them.

```bash
/var/lib/autosd-test/board-podman-smoke.sh tmpfs      # zero board mutation, run this first

# Only after that passes: partition and format the previously-empty 32 GB UFS LUN by hand.
# <device> is the one eyes-on decision here — confirm it against `lsblk` output (size,
# absence of children/partitions) before running anything below. sgdisk and mkfs.btrfs
# themselves are not eyes-on steps, just the plumbing that follows that decision.
lsblk
sgdisk -n 1:0:0 -t 1:8300 -c 1:autosd-store <device>          # e.g. /dev/sdc — partition 1
mkfs.btrfs -f /dev/disk/by-partlabel/autosd-store             # the label now resolves

/var/lib/autosd-test/board-podman-smoke.sh btrfs /dev/disk/by-partlabel/autosd-store
```

`sgdisk` (partitioning) and `mkfs.btrfs` (formatting) both come from an EPEL 10 repo the
image manifest adds — the AutoSD 10 repos alone do not carry `btrfs-progs`/`gdisk`. `btrfs`
is the only step in this task that writes to physical storage; the partition-then-format
sequence above is deliberately manual and not run by the script itself, so the "which device"
decision stays with the operator's eyes, not buried in a command the operator has to trust.

A genuine `tmpfs` pass stamps `/run/x5h-smoke-tmpfs-passed` before printing
`SMOKE_tmpfs_PASS`; `btrfs` checks for that stamp before touching anything and prints
`SMOKE_btrfs_TMPFS_GATE_FAIL` and exits if it is missing. The stamp lands in `/run` and
nowhere else because this boot has no initrd — U-Boot loads only `Image` and the DTB, so PID
1 mounts `/run` itself as an API tmpfs — which is what makes the interlock genuinely
boot-scoped: it is cleared by a power cycle, not merely by an `rm`. (If `/run` were ever
*not* a mount here, the stamp would instead land on the NFS server's copy of the export and
would survive power cycles and sessions, silently pre-authorizing a `btrfs` write on a cold
boot — so this is worth re-confirming if the boot path ever changes.) A failed unmount at the
end of a `tmpfs` run withholds the stamp even though `SMOKE_tmpfs_PASS` still prints (the
podman/network result it reports is genuine; only the "board left clean" promise the stamp
makes is at stake) — its own `SMOKE_tmpfs_UMOUNT_WARN` marker says so; a failed stamp write
itself (or a `/run` that unexpectedly isn't tmpfs) is caught too, as `SMOKE_<mode>_STAMP_WRITE_FAIL`,
so `SMOKE_tmpfs_PASS` can never print over a stamp that silently didn't land. If you
deliberately need to run `btrfs` alone — e.g. after a reboot cleared the stamp but you
already know `tmpfs` is fine — either re-run `tmpfs` again (it costs nothing) or
`touch /run/x5h-smoke-tmpfs-passed` by hand to override.

The networking check inside each phase auto-detects which kernel is running (`uname -r`'s
`-autosd` suffix) and branches accordingly — it no longer has one fixed shape:

- **On the BSP kernel**, it is the same two-stage, informational-then-decisive shape the
  retired GATE5 used: a port-published attempt (`curl http://127.0.0.1:8080/`) runs first
  and is **informational only** — it prints `SMOKE_<mode>_NET_PORT_OK` if it unexpectedly
  succeeds, but its failure never sets the script's fail state. It is expected to fail every
  time under the currently-shipped `firewall_driver = "none"`: netavark's `none` driver never
  installs a DNAT rule, so a published port is unreachable by construction. The check that
  actually decides `SMOKE_<mode>_NET_OK` vs. `SMOKE_<mode>_NET_FAIL` is the
  direct-container-IP path — `podman inspect`'s `.NetworkSettings.Networks` range form — run
  automatically, not left for the operator to trigger by hand.
- **On the rebuilt kernel**, the port-published attempt is decisive instead:
  `60-nftables.conf`'s nftables driver does install the DNAT rule, so a dead published port
  there is a real regression, and `SMOKE_<mode>_NET_PORT_FAIL` sets the fail state — the live
  equivalent of `GATE6_NFT_PORT_FAIL`. The direct-container-IP path still runs afterward as a
  second, independent confirmation and can also fail. A third check then runs, rebuilt kernel
  only: a busybox container's `wget -T 10` against a host-PC listener across the board LAN
  (`SMOKE_EXT_URL`, default `http://192.168.0.1:8099/`; `SMOKE_EXT_URL=skip` records
  `SMOKE_<mode>_SNAT_SKIPPED` instead of running it), proving container→external is
  masqueraded — `SMOKE_<mode>_SNAT_OK`/`SMOKE_<mode>_SNAT_FAIL`, the live equivalent of
  `GATE6_SNAT_OK`/`GATE6_SNAT_FAIL`.

If `SMOKE_<mode>_NET_FAIL` prints on the BSP kernel, both of its paths already failed
automatically; look at `podman0`/`veth0` state and `podman` logs next, not at the firewall
driver — `50-x5h.conf` already ships the only value the BSP kernel's netavark accepts.

Each phase prints `SMOKE_<mode>_STORE_FS=<fstype>` right after its mount succeeds (mirroring
`gate-guest.sh`'s `GATE2_STORE_FS`/`GATE3_STORE_FS`/`GATE4_STORE_FS`) — check it reads
`tmpfs` / `ext4` / `btrfs` for the `tmpfs` / `ext4loop` / `btrfs` modes respectively (yes,
`ext4loop`'s own store fstype reads `ext4` — the mode name describes how the store is backed,
not the filesystem on it), not whatever was mounted underneath, before trusting a later
`_PASS`. `ext4loop` and `btrfs` both additionally assert this themselves, machine-enforced
rather than left to the operator's eyes (mirroring how `qemu-gate.exp` itself requires
`GATE4_STORE_FS=btrfs`): a mount that succeeds but isn't actually the expected filesystem
(e.g. a `btrfs` `$DEV` typo onto a device carrying a real filesystem) fails loudly as
`SMOKE_<mode>_STORE_FS_FAIL`, before any `podman load` gets a chance to write to it. Every
run ends in one of: `SMOKE_<mode>_PASS`; `SMOKE_<mode>_FAIL` (a podman or network check
failed); `SMOKE_<mode>_MODPROBE_FAIL`; `SMOKE_<mode>_MOUNT_FAIL`; or, mode-specific,
`SMOKE_<mode>_DEV_FAIL` (`btrfs` only, bad block device), `SMOKE_<mode>_TMPFS_GATE_FAIL`
(`btrfs` only, no prior `tmpfs` pass), `SMOKE_<mode>_IMG_FAIL`/`SMOKE_<mode>_MKFS_FAIL`
(`ext4loop` only, backing-file `truncate`/`mkfs.ext4` failed — `MKFS_FAIL` is *expected* on
the current image, which ships no `e2fsprogs`; see Board bring-up step 3), or `SMOKE_<mode>_STORE_FS_FAIL`
(`ext4loop`/`btrfs`, mounted but the wrong filesystem) — except an invalid or missing mode
argument, which prints a plain `usage: ...` line and exits 2 with **no** `SMOKE_` marker at
all, since the script hasn't chosen a `$MODE` to prefix one with yet. Grep for the full set;
if you see none of them, the run stopped before producing anything trustworthy — treat that
the same as a failure, not as a pass.

Site values — server IP, export paths, the `ip=` kernel argument, and the DTB filename —
live in `x5h-work/HANDOFF.md` on the operator's machine and are never committed to this
repo.

## Troubleshooting

(findings recorded as discovered)

| Symptom | Cause | Fix |
| --- | --- | --- |
| `aib build` fails during depsolve with `No match for argument: btrfs-progs`, `No match for argument: gdisk` (`osbuild.solver.exceptions.MarkingError: ... missing packages: btrfs-progs, gdisk`) | Both packages were moved out of the AutoSD 10 / CentOS Stream 10 repos upstream and are not present in `baseos`, `appstream`, `automotive`, `autosd`, or `compose`. btrfs is the only viable persistent container store on the X5H's BSP kernel (no `CONFIG_XFS_FS`, no `CONFIG_F2FS_FS`, ext4 has no security xattrs), so `btrfs-progs` is not optional; `gdisk` partitions the board's UFS LUN for it. (The plan's Task 2 note predicted `iptables-nft` would need the same treatment — it did not: `iptables-nft` resolves fine from the existing repos.) | Added EPEL 10 as an `extra_repos` entry in `aib/vars.yml` (`id: epel10`, `baseurl: https://dl.fedoraproject.org/pub/epel/10/Everything/aarch64/`, `gpgcheck: false`). `gpgcheck: false` is deliberate: EPEL is signed with its own key, not the CentOS Stream 10 / Red Hat 10 keys aib trusts globally via `distro_gpg_keys`, and aib's repo schema has no per-repo `gpgkey` field to add a second trusted key just for this repo. |
| `aib build` gets through depsolve and RPM install, then fails on the `add_files` copy: `org.osbuild.copy: ... cp: cannot create regular file '/run/osbuild/tree/etc/containers/containers.conf.d/50-x5h.conf': No such file or directory` | `org.osbuild.copy` (what `add_files` compiles down to) does not create parent directories, and nothing else in the pipeline creates `/etc/containers/containers.conf.d/` — `/etc` itself exists (aib's `init_rootfs_dirs_stage` creates it), but not this subtree. aib does have logic that auto-creates parent directories for `add_files` (`_ensure_parent_directory` in `aib/simple.py`), but it only fires on the glob/path-preserving code path and is never reached for an explicit `source_path` → `path` pair like ours. | Added a `make_dirs` entry for `/etc/containers/containers.conf.d` (`parents: true`, `exist_ok: true`) to `aib/x5h-rootfs.aib.yml` — the same shape `_ensure_parent_directory` itself constructs, aib's own idiom for this. Confirmed from `files/simple.mpp.yml`'s `rootfs` pipeline that the `org.osbuild.mkdir` stage `make_dirs` generates runs strictly before the `org.osbuild.copy` stage `add_files` feeds (mkdir is stage index 4, copy is stage index 6, and osbuild runs a pipeline's stages in the order the manifest lists them), so the directory exists by the time the copy runs. **Do not instead move the drop-in to `/usr/share/containers/containers.conf.d/`** — that path is not one of the documented `containers.conf` search paths (`/usr/share/containers/containers.conf`, `/etc/containers/containers.conf`, `/etc/containers/containers.conf.d/*.conf`, per `containers.conf(5)`); the build would go green and the drop-in would silently never apply, so GATE5 would fall back to `firewall_driver="none"` for a reason unrelated to the missing `NF_TABLES` the gate is actually there to probe — a wrong finding on the exact question this gate exists to answer. |
| The build succeeds and the gate boots, but never reaches a login prompt; the console shows a repeating cycle of `Timed out waiting for device dev-d…SP.device - /dev/disk/by-label/ESP.` → `Dependency failed for boot-efi.mount` → `Dependency failed for local-fs.target` → `Starting emergency.service - Emergency Shell Override - Reboot...` → `systemd-shutdown[1]: Syncing filesystems and block devices.`, and `qemu-gate.exp` eventually fails with `FATAL: no login prompt within 1800s` (or, after the boot-loop guard below, `FATAL: guest rebooted N times without reaching a login prompt`) | **Not fstab** (an earlier fix neutralized fstab, which was necessary but not sufficient — the cycle continued). aib itself generates and installs an *enabled* `boot-efi.mount` unit into the image (`computed-vars.ipp.yml` copies it to `/usr/lib/systemd/system/boot-efi.mount`, requiring `What=/dev/disk/by-label/ESP`, and adds it to `image_enabled_services`), gated by `use_efipart_mount`/`use_efipart`. Neither the bare ext4 export nor the board's NFS root has an ESP partition, so this unit times out (30 s), `local-fs.target` fails, and AutoSD's `emergency.service` — **"Emergency Shell Override - Reboot"** — reboots the guest instead of dropping to a shell. Forever: 37 reboots were observed in one CI run before the harness's fixed budget ran out. Because this unit ships *inside the rootfs* (not something the gate scripts add), it is not gate-specific — it would have hit the board's NFS-root boot too, over serial, in the one-shot session with the operator present. (`selinux-bools.service` also fails in the same console output, right next to this cycle — see the next row; it is not the cause of the loop and should not be conflated with it.) | Set `use_efipart: false` in `aib/vars.yml`. `computed-vars.ipp.yml` only computes `use_efipart` from `use_ukiboot` "if not already in locals()", so a `--define-file` override wins and `use_efipart_mount` (an unconditional `mpp-eval: use_efipart`) follows it to `false`, which stops `boot-efi.mount` from being generated or enabled at all. Every reference to the EFI partition/device (`build.ipp.yml`'s `base_partitions`, `content.ipp.yml`'s `disk_yaml` partition table, `image.ipp.yml`'s `mkfs.fat` stage and mount/copy device map) lives inside the disk-image-building `image` pipeline, which neither export path exercises (`aib build --tar` never requests a disk output; the gate boots the ext4 export directly via `-kernel`; the board netboots the BSP kernel) — so this only removes an unused disk-image code path, not rootfs content. `use_ukiboot` stays at its default (true); nothing it gates depends on `use_efipart`. **Kept the fstab neutralization too** — the image's fstab genuinely was written for a disk image, and it keeps the gate and board paths symmetric — just don't credit it with fixing this particular loop; a different root cause was hiding behind it. Also hardened `qemu-gate.exp` with a boot-loop guard: it counts `Booting Linux on physical CPU` (the kernel's first boot line, printed once per boot) and fails fast with a distinct diagnostic on the third occurrence, instead of waiting out the full 1800 s budget to notice a loop that was obvious by the second boot — this cost ~2.5 minutes to diagnose the `boot-efi.mount` cause above, instead of 30. |
| `GATE1_SYSTEMD_STATE=degraded`, with exactly two failed units: `selinux-bools.service` and `ukiboot-set-success.service` | Both expected on this gate/kernel combination, not a bug. `selinux-bools.service` (`[FAILED] Failed to start selinux-bools.service - Enable selinux booleans.`) fails because the BSP-mimic kernel has no `CONFIG_SECURITY_SELINUX`, so `setsebool` has nothing to operate on — itself a real survey answer about running AutoSD userspace on the BSP kernel. `ukiboot-set-success.service` (`"Mark boot as successful in ukibootctl partition"`) fails because `use_efipart: false` (see the `boot-efi.mount` row above) means there is no ukibootctl partition for it to write to. Neither causes the earlier reboot loop — that was `emergency.service` reacting to the (now-fixed) `boot-efi.mount` failure, not either of these two units; they just appear adjacent to it in the console log and are easy to conflate with it. | None needed; recorded here so `degraded` doesn't alarm the board operator and these two failed units aren't mistaken for a live problem. |
| `GATE3_FAIL` / `GATE4_FAIL` with `Error: ... dial tcp [::1]:443: connect: connection refused` (pinging a registry literally named `localhost`), even though the console shows `Loaded image: docker.io/library/x5h-captest:latest` immediately above it | `gate-guest.sh` hardcoded the loaded captest image as `localhost/x5h-captest:latest`, matching what `podman load` produced on the dev host Task 4 was reviewed on. This guest's podman normalizes the same tar to `docker.io/library/x5h-captest:latest` instead — tag normalization on `load` differs across podman builds/versions, so it was never safe to hardcode. The subsequent `podman run --rm localhost/x5h-captest:latest ...` found no local image and tried to pull from a registry named `localhost`. Separately, `GATE2_EXT4_UNEXPECTED_PASS` rested on `podman load`'s exit status alone, unlike GATE3/GATE4's `load` **+** `getcap` check — a `load` that silently dropped the capability xattr would still have reported a "pass". | `gate-guest.sh` now discovers the loaded tag via `podman images` in all three of GATE2/GATE3/GATE4 (the same pattern GATE5 already used for busybox), guarding against an empty capture before ever calling `podman run`. GATE2 now also runs the same `run` + `getcap` check GATE3/GATE4 have, so `GATE2_EXT4_UNEXPECTED_PASS` requires the capability to actually be readable in a running container, not just a `load` that exited 0 — a `load`-succeeds-but-`getcap`-fails outcome now reports `GATE2_EXT4_FAIL_OK` instead, since that is still the constraint manifesting, just silently. |
| Console shows `Error: netavark: Must provide a valid firewall backend, got iptables` right after GATE5's first attempt, then the fallback path succeeds and `GATE5_NONE_OK` prints | This image resolves **netavark 2.0.0**. CentOS Stream 10's AppStream repo also carries netavark 1.16.0 and 1.17.2, which still had an `"iptables"` firewall backend (confirmed against `containers/netavark`'s own `src/firewall/mod.rs` at each of those git tags) — but 2.0.0 removed it; only `"firewalld"`, `"nftables"`, and `"none"` are recognized `firewall_driver` values in this netavark, and `"iptables"` is rejected outright as a config-validation error, regardless of what kernel modules are loaded. Separately, `"nftables"` would not work on this kernel anyway (no `CONFIG_NF_TABLES`), and `"firewalld"` needs a running dbus/firewalld daemon this image does not configure — so `"none"` is the only value both accepted by this netavark and functional here, which GATE5 confirmed empirically (`podman0` bridge up, `veth0` in forwarding, direct-container-IP curl succeeding). | `50-x5h.conf` now ships `firewall_driver = "none"` directly instead of `"iptables"`. Reasoning: the board runs this same config, and shipping a value this netavark rejects outright would burn time in the one-shot board session on a failure already known in advance. (`board-podman-smoke.sh` initially only printed a hint for the operator to retry the direct-container-IP path by hand; a later fix gave it the same automatic port-published-then-direct-IP fallback structure as GATE5 itself, so the board no longer depends on the operator remembering to do that manually — see the Board bring-up section.) Regression detection survives no longer shipping `"iptables"`: GATE5's own two-stage structure (try a port-published container, then the direct-IP fallback) actively probes real networking behavior regardless of the starting config, so a future regression in the `none`-driver path itself still shows up as `GATE5_FAIL`. What is no longer independently re-confirmed on every run is specifically whether this netavark still rejects the string `"iptables"` — now a documented, version-pinned fact instead of a per-run probe; it would only need revisiting if the resolved netavark package version itself changes. |
| Board console goes silent / root filesystem I/O stalls shortly after boot, with no further output and no recovery over serial | **Not something the QEMU gate can exercise or catch** — this is a board-only, NFS-root-only risk. aib enables `NetworkManager.service` (only `NetworkManager-wait-online.service` is masked); in the gate this is harmless because root is `/dev/vda`. The board's root is NFS over the interface the kernel `ip=` parameter configured, this boot path has no initrd (`uboot/autosd-boot.env` loads only `Image` + DTB), so `nm-initrd-generator` never runs and no `.nmconnection` profile matching that static config exists anywhere in the image. NM starting on the NFS-root NIC with no matching profile is a classic NFS-root wedge: if it reconfigures the interface, root I/O stalls with no local recovery — every binary needed to fix it lives on the filesystem that just went away. Honest caveat: NM's connection-assumption logic *may* leave an already-configured interface alone, in which case nothing observable happens; this could not be confirmed or ruled out off-board. | `stage-nfs-rootfs.sh` masks `NetworkManager.service` in the staged NFS root (`ln -sf /dev/null $DEST/etc/systemd/system/NetworkManager.service`, the same mechanism `systemctl mask` itself uses, and the same one aib already applied to `NetworkManager-wait-online.service`) — applied at staging time, not by rebuilding the image, so it covers the board without touching the gate path at all. Nothing on the board needs NM: the kernel `ip=` parameter already configured the NIC, and netavark/`podman0` does not depend on it (proven in the gate, where GATE5 passed alongside a running NM). This is a deliberate gate/board divergence, in the safe direction, on an axis the gate structurally cannot see — if this row is ever "fixed" by re-enabling NM to match the gate, re-read this row first. |
