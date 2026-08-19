# AutoSD on R-Car X5H (Strategy A: BSP kernel + AutoSD userspace)

Non-ostree AutoSD 10 rootfs for the R-Car X5H (`r8a78000` / `ironhide`) board,
booted with the unmodified Renesas BSP kernel 6.1.102 over the existing netboot
path (TFTP kernel + NFS root). Validated off-board first by a QEMU gate that
boots the rootfs under a **BSP-constraint-mimic kernel** — a 6.1.y LTS kernel
carrying the same feature gaps as the BSP kernel (no SELinux, no ext4 security
xattrs, no nftables, no erofs) — so every container-runtime question is
answered before board time.

> **Where the gate runs.** The gate's CI workflow is not in this repository. It
> needs an arm64 runner large enough to boot an aarch64 guest under TCG, which
> this repository's runners do not provide, so it lives on the fork the platform
> was developed on — `youtalk/openadkit`,
> `.github/workflows/autosd-x5h-rootfs.yaml`. Everything the gate *runs* is
> here, under `scripts/`, and replays on a dev host; the sections below that
> refer to "CI" or pass `--repo youtalk/openadkit` mean that fork's runs. Board
> bring-up is manual either way — no CI has the hardware.

## Folder Structure

- `aib/`: automotive-image-builder manifest (distro `autosd10-sig`)
- `config/`: containers.conf drop-in shipped into the image
- `kernel/`: mimic-kernel config fragment + build script (QEMU gate only, never for the board)
- `scripts/`: QEMU gate harness and board staging/smoke scripts
- `uboot/`: `bootcmd_autosd` template (site values are filled at session time, not committed)

## QEMU gate semantics

The gate boots the rootfs export under the BSP-constraint-mimic kernel in
QEMU, logs in as root, runs `scripts/gate-guest.sh` inside the guest, and
judges the run by grepping the session log for a fixed set of markers.
`gate-guest.sh` emits the markers; `qemu-gate.exp` judges them by string
match — the two must stay in exact sync.

`gate-guest.sh` never exits nonzero mid-way: every assertion prints a marker
and `GATE_DONE` always prints, no matter which gates failed. All judgement
happens on the host side (`qemu-gate.exp`), by grepping the captured log for
these markers.

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

Two markers are deliberately **either/or**, not single-verdict:

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

`GATE3_STORE_FS=tmpfs` and `GATE4_STORE_FS=btrfs` exist because GATE3/GATE4's
mount step (`mount -t tmpfs …` / `mkfs.btrfs` + `mount /dev/vdb …`) checks no
exit status and `gate-guest.sh` never aborts on a failed mount — without this
check, a silently-failed mount would leave `/var/lib/containers` on whatever
was mounted there before (typically the ext4 root), and the podman probe that
follows would still validly pass or fail, just against the wrong filesystem,
printing a `GATE3_TMPFS_OK` / `GATE4_BTRFS_OK` that didn't actually exercise
tmpfs/btrfs at all.

The overall gate (`qemu-gate.exp`) exits 0 only if `GATE1_LOGIN_OK`,
`GATE3_TMPFS_OK`, `GATE3_STORE_FS=tmpfs`, `GATE4_BTRFS_OK`,
`GATE4_STORE_FS=btrfs`, `GATE_DONE`, one of the GATE2 accepted markers, and
one of the GATE5 accepted markers are all present in the session log.

`qemu-gate.exp` waits for the guest-side run with an inactivity timeout (15
minutes with no new `GATE<n>_…` marker line, re-armed on every marker) rather
than one fixed budget for the whole run: the run's total length varies with
TCG emulation speed and isn't a meaningful thing to cap as a single number,
but a guest that goes genuinely silent, or dies outright, still fails fast
with a clear diagnostic instead of a generic "gate did not finish". The
15-minute figure is not arbitrary: GATE5 is the longest stretch with no
re-arming marker output (every command in it is output-suppressed), and its
two 30-iteration poll loops alone cap at 210s each — 420s of pure
network/sleep wall-clock — before accounting for podman process-spawn
overhead on top. See the comment at `qemu-gate.exp`'s `inactivity_timeout`
declaration for the full arithmetic; it is coupled to GATE5's poll bounds in
`gate-guest.sh`, not an independent number.

## Gate verdict: survey §7 answers

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

## Running locally

The same gate CI ran replays on an x86 dev host. Two reasons this is worth
doing beyond interactive debugging: it is the only place the tar → ext4
reassembly gets exercised outside CI, and that reassembly is exactly what
`scripts/stage-nfs-rootfs.sh` does for the board's NFS root (`tar --xattrs
--xattrs-include='*.*' -xf <tarball> -C <dest-dir>`) — so a green local
replay is corroborating evidence for the board staging path, not just a
debugging convenience. It also leaves a local copy of `x5h-rootfs.tar` on
disk, which is what `stage-nfs-rootfs.sh` consumes at board time.

The replay needs three inputs: the rootfs tar, the mimic kernel `Image`, and
the two test-image tars. Build them from source (below) or download a bundle
CI already produced. **Neither route needs the Renesas BSP or any
credential-gated download** — the rootfs resolves from public AutoSD 10 and
EPEL 10 repos, the mimic kernel is a stock 6.1.y LTS from kernel.org (it is
deliberately *not* the BSP kernel; see `kernel/bsp-mimic.config`), and the
test images come from `public.ecr.aws` and `quay.io`. The one BSP-derived
input this platform has is `<bsp-rootfs-dir>` under "Board bring-up" below,
which the replay never touches.

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

# 2. The BSP-constraint-mimic kernel. The script pins the newest 6.1.y
#    longterm release from kernel.org's releases.json, merges
#    kernel/bsp-mimic.config over arm64 defconfig, then *asserts* the whole
#    constraint set actually landed — a defconfig that quietly re-enabled
#    e.g. EXT4_FS_SECURITY fails the build here rather than producing a
#    kernel that lets GATE2 sail past the blocker it exists to probe.
kernel/build-mimic-kernel.sh /tmp/x5h-mimic

# 3. The two test images. make-test-images.sh also verifies the captest
#    archive really carries a security.capability PAX record, so an xattr
#    silently dropped at build time cannot reach the gate disguised as a
#    GATE2 finding.
scripts/make-test-images.sh /tmp/x5h-testimages
```

Two things to know before running these on an x86_64 host, because CI
exercises neither — CI is native arm64 (`ubicloud-standard-16-arm`):

- **Every output is aarch64.** Steps 1 and 3 run aarch64 containers, so they
  need `qemu-user-static` binfmt registered (`sudo apt install
  qemu-user-static binfmt-support`, or `docker run --privileged --rm
  tonistiigi/binfmt --install arm64`). Step 2 cross-compiles instead and
  needs `gcc-aarch64-linux-gnu`; `build-mimic-kernel.sh` selects the cross
  prefix itself from `uname -m`.
- **Budget generously, but don't trust a figure.** CI builds all three
  natively on arm64 in about 25 minutes end to end, QEMU gate included (run
  30842769817, 18:46:46 → 19:12:20). There is no verified x86 number: the aib
  build and the two container builds run under binfmt there, so expect
  materially longer and budget accordingly rather than planning against a
  number nobody has measured.

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
       --branch feat/autosd-x5h-rootfs --status success --limit 1 \
       --json databaseId --jq '.[0].databaseId')"

# The workflow stages a flat bundle before upload — one `testimages/`
# subdirectory, everything else at the top level:
#   Image  x5h-rootfs.tar  x5h-gate.log  testimages/busybox-oci.tar  testimages/captest-docker.tar
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
`qemu-gate.exp` interpreter), and `e2fsprogs` for `mkfs.ext4`; plus `gh`
(authenticated) if you took the download route. CI's "Install host tools"
step installs `podman`, `skopeo`, `qemu-system-arm`, `qemu-utils`, `expect`,
`flex`, `bison`, `libssl-dev`, `libelf-dev`, and `bc` — `e2fsprogs` and `gh`
are not in that list because GitHub-hosted runners ship both preinstalled
already; the `flex`/`bison`/`libssl-dev`/`libelf-dev`/`bc` portion is the
aib/kernel/container-build toolchain from "Building the inputs" above.

First point these three at whichever route you took. They are the only
difference between the two:

```bash
cd platforms/autosd/x5h   # the relative paths below, and ./scripts/... later, need this

# Built from source:
TAR=aib/x5h-rootfs.tar
KERNEL=/tmp/x5h-mimic/Image
TESTIMAGES=/tmp/x5h-testimages

# ...or from a downloaded bundle. `find` rather than fixed paths, because
# the lookups have to be depth-agnostic — and note TESTIMAGES resolves to
# the bundle's `testimages/` subdirectory, not the bundle root.
TAR="$(find /tmp/x5h-bundle -name x5h-rootfs.tar)"
KERNEL="$(find /tmp/x5h-bundle -name Image)"
TESTIMAGES="$(dirname "$(find /tmp/x5h-bundle -name busybox-oci.tar)")"
```

Everything to this point runs as your own user. Loop-mounting the ext4 export
(step 1's `mount`/`tar`/`umount`) and running `qemu-gate.exp` (step 3) need
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
# extended attributes on extract (exit 0, no warning), which would make
# GATE2 fail for the wrong reason (the archive never carried
# security.capability into the export) instead of the real one
# (EXT4_FS_SECURITY missing in the mimic kernel).
sudo tar --xattrs --xattrs-include='*.*' -xf "$TAR" -C "$mnt"
sudo umount "$mnt"
rmdir "$mnt"

# 2. Inject the test payload. Use the script, not a hand-copy: besides the
#    two test tars and gate-guest.sh, it also neutralizes /etc/fstab
#    (preserving the original as fstab.image) — skip that and the guest
#    reboot-loops on the stock fstab's ESP entry (see Troubleshooting).
./scripts/inject-test-images.sh /tmp/x5h-replay.ext4 "$TESTIMAGES"

# 3. Run the gate. /tmp/x5h-blank.img is deliberately not pre-created here:
#    run-qemu-gate.sh makes it itself (`qemu-img create -f raw ... 8G`) when
#    the path doesn't exist yet, the same fallback CI relies on rather than
#    pre-creating it — which is why qemu-img (qemu-utils) is a listed
#    prerequisite above, not an optional one.
#    On an x86 host, run-qemu-gate.sh's aarch64+/dev/kvm check is always
#    false, so this is cross-arch TCG — materially slower than CI's
#    same-arch TCG (~430 s of guest time in run 30730519760, per "Gate
#    verdict" above). There is no verified local number for cross-arch TCG;
#    expect it to run considerably longer and budget accordingly rather than
#    trusting a specific figure. qemu-gate.exp's inactivity timeout re-arms
#    on every marker, so a slow-but-progressing run will not be killed
#    early.
sudo ./scripts/qemu-gate.exp ./scripts/run-qemu-gate.sh \
  "$KERNEL" /tmp/x5h-replay.ext4 \
  /tmp/x5h-blank.img /tmp/x5h-local-gate.log

# 4. Read the result the same way CI's "Show gate markers" step does.
grep -E 'GATE[0-9_]+' /tmp/x5h-local-gate.log
```

`qemu-gate.exp` itself exits 0 only once every required marker from the
vocabulary table above is present in the log (`GATE1_LOGIN_OK`, both
`GATE3`/`GATE4` `_STORE_FS=`/`_OK` pairs, `GATE_DONE`, one of the two
accepted GATE2 verdicts, one of the two accepted GATE5 verdicts) — check
`echo $?` after it returns, or just compare the `grep` output above against
the marker table and the "Gate verdict" table for the expected line-for-line
match.

## Board bring-up

Board time is scarce and one-shot — no rerun scheduled. The order below encodes the plan's
board-safety invariants; do not reorder it.

### 1. Stage the AutoSD NFS root

The two inputs come from wherever "Running locally" above got them — built from source, or
unpacked from a CI bundle. The bundle is flat but not entirely flat: the tarball sits at the
top level while the two test images sit one level down, under `testimages/`. Resolve both by
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
`tftp ${kernel_addr_r} Image` to a load at `${loadaddr}`: a wrong-address load that still
looks like a working command. Run `printenv kernel_addr_r fdt_addr_r` first and, if either
is "not defined", `setenv` it to the matching literal address read out of the `printenv`
backup taken at the start of the session (never a guessed address). The rest
(`autosd_export_path`, `bootargs_bsp`, `board_ip_config`, `dtb_file`) are operator-supplied
from `x5h-work/HANDOFF.md` (not committed to this repo) and must all be `setenv` at the
prompt **before the first line of the template**, not merely before `bootargs_autosd` —
`autosd_export_path` is consumed by the *first* line (`autosd_nfsroot`), which is unquoted
and therefore expands immediately, exactly like the double-quoted `bootargs_autosd` line
that follows it. Setting `autosd_export_path` only after `autosd_nfsroot` has already run
still bakes an empty export path into it (`nfsroot=<ip>:,nfsvers=3`), and that string is
plausible enough to pass a casual glance. After entering all three lines, read back
`printenv autosd_nfsroot bootargs_autosd` and check that the export path and the `ip=`
config are actually present in the output — not just that the strings "look complete" —
then boot the AutoSD NFS root with:

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

Once logged in, `systemctl is-system-running` reporting `degraded` is expected, not a fault
— the QEMU gate reproduces the identical state from exactly two known-benign failed units
(`selinux-bools.service`: no SELinux in this kernel; `ukiboot-set-success.service`: no
ukibootctl partition, since this image ships `use_efipart: false` — see the Troubleshooting
table below for both). Neither should be chased as a live problem.

At the end of the session, re-verify the unmodified BSP boot path still works (power cycle,
default `bootcmd`, BSP NFS root) before releasing the board.

### 3. On-board podman smoke: tmpfs before btrfs

`scripts/board-podman-smoke.sh` is staged onto the NFS root under `/var/lib/autosd-test/`
by step 1 — **not** on `PATH`, so invoke it by absolute path (a `command not found` at a
1.8 Mbps serial prompt costs real time). It runs in two phases, and the order is an enforced
invariant, not just a documented one: `btrfs` refuses to run unless a `tmpfs` run has already
passed on this boot.

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

The networking check inside each phase is two-stage, mirroring `gate-guest.sh`'s GATE5, and
only the second stage is decisive: a port-published attempt (`curl http://127.0.0.1:8080/`)
runs first and is **informational only** — it prints `SMOKE_<mode>_NET_PORT_OK` if it
unexpectedly succeeds, but its failure never sets the script's fail state. It is expected to
fail every time under the currently-shipped `firewall_driver = "none"`: netavark's `none`
driver never installs a DNAT rule, so a published port is unreachable by construction, proven
in the gate's own green run (the port-published attempt polled ~78 s with zero successful
curls before the fallback below succeeded). The check that actually decides `SMOKE_<mode>_NET_OK`
vs. `SMOKE_<mode>_NET_FAIL` is the direct-container-IP path — `podman inspect`'s
`.NetworkSettings.Networks` range form, the same one the QEMU gate's own fallback uses — run
automatically, not left for the operator to trigger by hand. If `SMOKE_<mode>_NET_FAIL` still
prints, both paths already failed automatically; look at `podman0`/`veth0` state and `podman`
logs next, not at the firewall driver — `50-x5h.conf` already ships the only value this
netavark accepts.

Each phase prints `SMOKE_<mode>_STORE_FS=<fstype>` right after its mount succeeds (mirroring
`gate-guest.sh`'s `GATE3_STORE_FS`/`GATE4_STORE_FS`) — check it reads `tmpfs` / `btrfs`
respectively, not whatever was mounted underneath, before trusting a later `_PASS`. `btrfs`
additionally asserts this itself, machine-enforced rather than left to the operator's eyes
(mirroring how `qemu-gate.exp` itself requires `GATE4_STORE_FS=btrfs`): a `$DEV` that mounts
successfully but isn't actually btrfs (e.g. a typo onto a device carrying a real filesystem)
fails loudly as `SMOKE_<mode>_STORE_FS_FAIL`, before any `podman load` gets a chance to write
to it. Every run ends in one of: `SMOKE_<mode>_PASS`; `SMOKE_<mode>_FAIL` (a podman or network
check failed); `SMOKE_<mode>_MODPROBE_FAIL`; `SMOKE_<mode>_MOUNT_FAIL`; or, `btrfs` only,
`SMOKE_<mode>_DEV_FAIL` (bad block device), `SMOKE_<mode>_TMPFS_GATE_FAIL` (no prior `tmpfs`
pass), or `SMOKE_<mode>_STORE_FS_FAIL` (mounted, but not actually btrfs) — except an invalid
or missing mode argument, which prints a plain `usage: ...` line and exits 2 with **no**
`SMOKE_` marker at all, since the script hasn't chosen a `$MODE` to prefix one with yet. Grep
for the full set; if you see none of them, the run stopped before producing anything
trustworthy — treat that the same as a failure, not as a pass.

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
