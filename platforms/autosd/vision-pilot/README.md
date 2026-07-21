# AutoSD + VisionPilot

Run [VisionPilot](https://github.com/autowarefoundation/autoware_vision_pilot)
(standalone, video input, ONNX Runtime CPU EP) as a Podman Quadlet service on an
AutoSD 10 aarch64 image, validated in QEMU before any R-Car Gen 5 board work.

## Folder Structure

- `aib/`: automotive-image-builder manifest for the AutoSD 10 image (target `qemu`)
- `components/`: Quadlet files run by podman + systemd inside the image
- `smoke/`: deterministic inference smoke test (pinned test data, log assertions)
- `scripts/`: QEMU launcher and CI serial-console harness

## Host Prerequisites (Ubuntu 24.04)

See "Host setup" below. aarch64 image builds happen in CI on native arm64
runners — automotive-image-builder only builds on the native architecture.

## Host setup

Install the emulation, container, and test tooling (Ubuntu 24.04):

```bash
sudo apt-get update && sudo apt-get install -y \
  qemu-system-arm qemu-efi-aarch64 qemu-utils podman qemu-user-static ffmpeg expect
```

Register the arm64 binfmt handler for `docker buildx` (cross-arch container builds):

```bash
docker run --privileged --rm tonistiigi/binfmt --install arm64
```

Verify (all five must succeed — S0 pass criteria):

```bash
qemu-system-aarch64 --version | head -1           # QEMU emulator version 8.2.2
podman --version                                  # podman version 4.9.3
ls /usr/share/AAVMF/AAVMF_CODE.fd                 # aarch64 UEFI firmware present
docker buildx ls | head -3                        # default builder lists linux/arm64
cat /proc/sys/fs/binfmt_misc/qemu-aarch64         # enabled
```

Verified versions on the reference host: QEMU 8.2.2, podman 4.9.3, expect 5.45.4,
docker buildx 0.31.2. `qemu-efi-aarch64` provides `/usr/share/AAVMF/`; the apt
`qemu-user-static` package and the `tonistiigi/binfmt` step both register the
aarch64 binfmt interpreter (`/usr/libexec/qemu-binfmt/aarch64-binfmt-P`).

## VisionPilot container image

The image is built from [autoware_vision_pilot](https://github.com/autowarefoundation/autoware_vision_pilot)
at the commit pinned in `smoke/visionpilot.env` (`VP_COMMIT`). VisionPilot is
**not vendored**; it is cloned at build time. Two small source fixes in
`patches/` **must be applied before `docker build`**, or the image is
headless-broken (aborts opening an X window) and exits non-zero on success:

```bash
. smoke/visionpilot.env
git clone "$VP_REPO" vp && (cd vp && git checkout "$VP_COMMIT")   # weights are regular files
for p in patches/*.patch; do (cd vp && git apply "$OLDPWD/$p"); done
docker build --build-arg TARGETARCH=amd64 -f vp/VisionPilot/docker/Dockerfile.cpu -t visionpilot:cpu-amd64 vp/VisionPilot
```

`TARGETARCH` must be passed explicitly (the Dockerfile defaults it to `amd64`, and
a plain native build does not auto-populate it). For an arm64 image build
`--build-arg TARGETARCH=arm64`, otherwise the build fetches the x64 ONNX Runtime
and fails to link.

Both patches are carried only until merged upstream (PRs to autoware_vision_pilot):

- `0001-visualization-open-local-window-lazily.patch` — `LocalDisplay` opens its
  OpenCV window lazily on first render, so a headless run (`visualization_on=false`,
  no `$DISPLAY`) does not abort in the constructor.
- `0002-return-zero-exit-on-clean-shutdown.patch` — `main` returns `0` on a clean
  shutdown (upstream returns the `bool` from `stop()`, i.e. exit 1 on success),
  so VisionPilot works as a Podman Quadlet `oneshot` service.

### Smoke test

`smoke/` runs a deterministic CPU inference over a pinned OpenLane clip and
checks the per-frame `plan:` log against `smoke/reference/`. Run locally:

```bash
./smoke/fetch-testdata.sh /tmp/vp-data 100
cp /tmp/vp-data/clip100.mp4 /tmp/vp-data/clip.mp4
cp /tmp/vp-data/speed100.txt /tmp/vp-data/speed.txt
docker run --rm -v /tmp/vp-data:/data:ro \
  -v "$PWD/smoke/config/vision_pilot.conf:/usr/share/visionpilot/config/vision_pilot.conf:ro" \
  -v "$PWD/smoke/config/vision_pilot_test.conf:/usr/share/visionpilot/config/vision_pilot_test.conf:ro" \
  visionpilot:cpu-amd64 2>&1 | tee /tmp/run.log
python3 smoke/assert-smoke.py --log /tmp/run.log --expect-frames 99 \
  --reference smoke/reference/reference-amd64.json --tolerance smoke/reference/tolerance.json
```

**Mount the two `.conf` files individually, not the whole `config/` directory** —
a directory mount would hide the image's build-generated `H.yaml` and
`homography_C_matrix.yaml` and crash at startup. An N-frame clip yields **N-1**
`plan:` frames (the AutoDrive model consumes the first frame as temporal
history), so `--expect-frames` is 99 for the 100-frame clip and 9 for the
10-frame clip.

## Running

Boot an AutoSD aarch64 disk image under QEMU:

```bash
./scripts/run-qemu.sh <disk.qcow2>
```

`run-qemu.sh` boots `qemu-system-aarch64 -machine virt` with the AAVMF UEFI
firmware, a virtio system disk, a user-mode NIC (SSH forwarded to
`localhost:2222`), and a serial console (`-nographic`; exit with `Ctrl-a x`).
It autodetects acceleration: `-accel kvm -cpu host` only when the host is
aarch64 **and** `/dev/kvm` is writable, otherwise `-accel tcg -cpu cortex-a76`
(see the Troubleshooting note on why not `-cpu max`). On the x86_64 reference
host it runs full TCG emulation, so an AutoSD boot to the `login:` prompt takes
on the order of a few minutes.

The invocation was validated on the reference host: with an empty disk QEMU
reaches the EDK II UEFI firmware and BdsDxe boot-device selection over the
serial console, confirming the machine type, firmware, virtio, and console
wiring. The image of record is the **aib-built AutoSD image** (see below);
build it in CI and boot it locally per the Stage 2 instructions.

## Troubleshooting

Findings from bringing the Quadlet smoke up on AutoSD 10 (recorded as discovered —
capturing these before the board phase is a primary purpose of this project):

- **QEMU `-cpu max` aborts under TCG.** Booting the AutoSD 10 ARMv9 UKI kernel with
  `-accel tcg -cpu max` makes QEMU abort (`regime_is_user: code should not be
  reached`). `run-qemu.sh` uses `-cpu cortex-a76`, which boots to login under TCG.
- **`add_files` destinations are restricted to `/etc` and `/usr`.** aib rejects
  paths under `/var`; the smoke data lives at `/etc/visionpilot/data`.
- **Mount the two `.conf` files individually, not the config directory.** A
  directory mount over `/usr/share/visionpilot/config` hides the image's
  build-generated `H.yaml` / `homography_C_matrix.yaml` and crashes VisionPilot.
- **`:Z` volume relabels work under AutoSD's SELinux.** AutoSD ships SELinux
  Enforcing by default; the Quadlet mounts the config and data with `:Z` and the
  container reads them cleanly — no manual policy was needed for read-only bind
  mounts from `/etc`.
- **podman + systemd double-log container stdout.** Each VisionPilot `plan:` line
  appears twice in `journalctl -u visionpilot.service` (podman's journald driver
  and the unit's stdout capture) as identical adjacent pairs; `assert-smoke.py
  --dedup-consecutive` collapses them.
- **`Type=oneshot` needs a zero exit.** Upstream VisionPilot returned the `bool`
  from `stop()` (exit 1 on success); patch `0002` makes it return 0 so the
  oneshot service reports `active`.
- **The numeric tolerance is a functional gate, not a tight regression gate.**
  It is calibrated from two amd64 runs (`assert-smoke.py --calibrate`), and the
  CPU pipeline is genuinely noisy run-to-run — multi-threaded ONNX Runtime FP
  reduction order, plus occasional MPC non-convergence that drops `tyre` to 0 —
  so the tolerances for `tyre`/`accel`/`vel` are wide relative to those fields'
  signal range. The check reliably catches crashes, wrong frame counts, and
  gross divergence (and `dist` stays discriminating), but is not a tight
  per-value regression gate. Tightening it would require pinning ORT to
  deterministic single-threaded execution before recalibrating.

Local validation of the CI-built image (x86_64 host, `-cpu cortex-a76`, TCG):
boots to `autosd-visionpilot login:` in ~2-3 min, `visionpilot.service` reaches
`active`, 9 planned frames are logged, and their values match the amd64 reference
within the per-field tolerance.

### CI virtualization (arm64 runner)

A probe job confirmed the arm64 CI runner does **not** expose `/dev/kvm` — verdict
`KVM_ABSENT` ([run](https://github.com/youtalk/openadkit/actions/runs/29624085273)).
The AutoSD QEMU boot in CI therefore runs under same-arch TCG (no KVM acceleration),
which is acceptable for the M=10 smoke. `scripts/run-qemu.sh` autodetects this: it
uses `-accel kvm` only when the host is aarch64 **and** `/dev/kvm` is writable,
otherwise `-accel tcg`.

### AutoSD nightly sample image

The `autosd.sig.centos.org/AutoSD-10/nightly/sample-images/` index redirects
downloads to an S3 bucket (`download.autosd.sig.centos.org`) that was returning
`NoSuchKey` for the currently-listed build — i.e. the HTML index was stale
relative to the pruned bucket, so the prebuilt nightly image could not be
fetched. The nightly boot is only a warm-up to learn AutoSD basics; the image of
record for this project is the reproducible **aib-built** image, which is boot-
tested both in CI (`autosd-vision-pilot-gate`) and locally, so a nightly image is
not required. Retry the nightly download later if a known-good QEMU baseline
from an unmodified image is wanted.
