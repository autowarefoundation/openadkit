# X5H NPU bring-up

What has to be true before the ONNX Runtime Renesas execution provider can
reach the NPU from AutoSD, in what order to do it, and how to get back if a
step goes wrong.

> **Status: the NPU runs on hardware.** Stage 0 (capture) executed 2026-08-10,
> Stage 1 reached NPU execution 2026-08-21, and Stage 2 — the AI-package
> bootloader — was flashed 2026-08-25, which is what made the NPU useful
> rather than merely reachable. Everything stated below as measured was
> measured on the board.
>
> **The kernel load address matters and nothing reports it.** Loading the
> kernel where the vendor documents is required; at other addresses the NPU
> runtime writes over it and the kernel takes an undefined-instruction oops
> during model load, with no diagnostic pointing anywhere near the cause.
>
> **The NPU device tree and the realtime cores are mutually exclusive.** The
> vendor NPU device tree omits the realtime core's reserved memory, so the two
> cannot run in one configuration — see [Where this stops](#where-this-stops).
> The NULL dereference that omission triggers in the BSP remoteproc driver is
> a vendor defect in its own right. In practice NPU verification runs on a
> separate board rather than reconciling the two; board roles are in
> [companion-host.md](companion-host.md).
>
> Measured NPU figures stay in the working area, outside this repository.

> **Numbers live elsewhere.** Flash offsets, device-tree addresses and
> interrupt numbers come from the vendor SDK and are not in this repository —
> same boundary as [cr52-slot-update.md](cr52-slot-update.md). This document
> carries the procedure, the reasoning and the traps. Read the values from
> the SDK's own flash-target definition at the time you run the steps.

## What the runtime actually needs

The execution provider reaches the hardware entirely from userspace. It opens
two families of device:

- **`/dev/npuc0`, `/dev/npuc1`** — the NPU clusters. These are ordinary UIO
  devices: the vendor's NPU device tree declares them `generic-uio` with a
  `linux,uio-name`, and the userspace side picks their register windows with
  `mmap` offsets that are multiples of the page size, which is the UIO map
  convention. See [uio.md](uio.md).

  **But those are not the names the kernel creates.** UIO names its device
  nodes `/dev/uioN` by probe order and puts the declared name in
  `/sys/class/uio/uioN/name`. Turning that name into `/dev/npuc0` takes a
  one-line udev rule: match `SUBSYSTEM=="uio"` and symlink `$attr{name}`. The
  same rule is also what makes the node openable by anything but root, since
  UIO creates its devices `0600 root:root`. `config/51-x5h-uio.rules` supplies
  it, verified on hardware 2026-08-11.
- **`/dev/cmem_other*`** — contiguous memory, served by an out-of-tree driver
  that has to be loaded once per boot. Its devices want a rule of their own,
  for the same permission reason: `config/52-x5h-cmem.rules`.

So there is no NPU kernel driver to find or write. What is missing is device
tree, and possibly one firmware component. The module and both udev rules are
done.

The naming rules were the easiest of those to overlook, because nothing about a
missing symlink points at udev. The device tree is right, the module is
loaded, the UIO device is bound and named — and the runtime still fails at
`open`, on a path that looks like it should exist.

## What the board already has

**The NPU firmwares are already flashed.** Both clusters' firmware is present
at the offsets the vendor's flash-target definition names, and matches the
package byte for byte across every S-record range — 139,230 chunks each, zero
mismatches. This was the step that looked like it would need a bench visit
and a serial flash writer. It does not: it is done.

**The UIO mechanism works.** 177 of the board's `generic-uio` nodes bind and
come up named, with mappings resolving to their declared addresses, once
`uio_pdrv_genirq` is given its `of_id` — which `config/x5h-uio.conf` now
supplies. Nodes that share one register window with separate interrupts bind
correctly, which is the pattern the NPU uses.

**One flash component differs.** The board carries the stock second-stage IPL
for the realtime cluster; the AI package ships a variant of it. The package
documents the change as switching DRAM ECC off *for improving performance*,
and ships the stock binary alongside so it can be put back. The manual
separately states that the SDK's IPL cannot run the package's samples, which
is in tension with a change described as a performance tweak. Nothing in the
documentation settles it, so Stage 1 below is written to find out cheaply
rather than to assume either way.

## Stage 0: capture what you would otherwise lose

Do this before anything else, and keep the results off the board. **Executed
2026-08-10**, so what follows is a record as much as an instruction.

- Read both realtime firmware slots. Stage 2 writes into the same address
  space, and one of these slots holds this branch's RPMsg responder — see the
  trap below.
- Read the flash region Stage 2 would rewrite, so a restore is a copy rather
  than a rebuild.
- Capture the U-Boot environment.

**Take whole-device images, not slot-sized ones.** The logical units involved
are small, so a full image costs little, and one image is then a superset of
both realtime slots, the bootloader payloads and the NPU firmwares at once —
with a single digest to check instead of one per extent, and no chance of
having read the wrong window. Hash on the board, stream the image off
compressed, and hash again after decompressing on the host: that checks the
transfer end to end, rather than checking the board against itself.

**The environment needs no serial.** `fw_printenv` is absent from this root
filesystem, but the saved environment is a plain run of `key=value` strings
behind a short header, living in one of the eMMC boot areas, so it can be read
as bytes from Linux and decoded on the host. Find it by searching those areas
for the name of a variable you know was set — the offset is a property of the
U-Boot build, so search rather than hard-code it. Doing it this way is
strictly better than a `printenv` transcript: it captures the stored form
rather than a rendering of it, and it costs no reboot and no console. Self-boot
can also be restored from `selfboot-env.txt` on the boot partition with no host
at all ([selfboot.md](selfboot.md)), so that remains belt and braces.

## Stage 1: bring the NPU up with no flash writes at all

Everything here is remote-capable. None of it touches flash.

1. **Merge the NPU device tree into the board's — this is where it stops.**
   The shape of the merge was never in doubt: the NPU cluster and UIO nodes, a
   root-level `/cmem` node carrying a `memory-region` phandle list, and the
   reserved-memory regions it refers to. Where those regions can go is in
   doubt, and badly enough that it is now a question for the vendor rather
   than a step. Read [Where this stops](#where-this-stops) before starting.

   Read the vendor's own NPU device tree first in any case. It is a complete,
   ready-made dtb rather than a fragment, which settles what the nodes look
   like without guesswork — and it also shows, by what it leaves out, that the
   vendor's NPU configuration and this branch's realtime work are not
   configured to run together.
2. **Build the cmem driver.** It is public and needs no SDK access:
   `github.com/renesas-rcar/cmem`, branch `rcar_gen5`, GPL-2.0. **Pin commit
   `e67f473c`, not HEAD.** HEAD adapts the driver to kernel 6.12 —
   `follow_pfnmap_start`, `vm_flags_set`, and the one-argument
   `class_create` — and every one of those postdates the 6.1 this board runs.
   `e67f473c` uses the older forms. Pin the SHA the way
   `kernel/build-bsp-kernel.sh` pins the BSP tree: the branch is mutable, the
   commit is the source of truth.

   **Done, 2026-08-10.** It builds unpatched, and needs no kernel rebuild: an
   out-of-tree module only wants a configured and built kernel tree at the
   matching version, and the tree left behind by an earlier
   `build-bsp-kernel.sh` run serves. Check the result by its `vermagic`
   against the running kernel rather than by the build succeeding — a module
   built against the wrong tree also compiles cleanly and then refuses to
   load. It loads and unloads on the board, and with no `/cmem` node present
   it creates only the default-CMA device, which is the expected shape of a
   half-configured system rather than a failure.
3. **Load it and confirm the devices appear.** Two mechanisms decide what
   appears, and they are easy to conflate. The driver's size parameter is an
   array, but it governs the devices carved out of the *default CMA* region;
   the `cmem_other` devices are a separate family whose **count and size come
   from the `/cmem` node's phandle list alone** — one device per phandle,
   each inheriting its reserved region's address and extent, neither
   overridable from the command line. So a `cmem_other` device of the wrong
   size is a device-tree defect, not a module-argument one.

   Confirm `/dev/npuc*` and `/dev/cmem_other*` both exist before going
   further — `board/npu-probe`-style output, not inspection by eye — and
   remember that their existence depends on the udev rules as much as on the
   device tree.

   **Done, 2026-08-11, as far as the device tree allows.** Both rules
   (`config/51-x5h-uio.rules`, `config/52-x5h-cmem.rules`) are verified on the
   board: 177 UIO name symlinks appear, and a fresh `cmemdrv` load with the
   rule in place produces `/dev/cmem0` at `0666` rather than `0600`. Only
   `cmem0` appears and no `npuc*` does, which is the expected shape while
   `/cmem` and the NPU nodes are absent — so what remains untested here is the
   device tree, not the plumbing around it. [uio.md](uio.md) records how the
   `npuc*` mode branch was exercised without an `npuc*` device.
4. **Run the critical experiment.** The ONNX Runtime release ships
   precompiled artifacts for two sample models, so this needs no compiler
   licence: deploy the runtime container, run the latency evaluation, and
   assert positively that the Renesas EP executed subgraphs rather than
   inferring it from a run that merely completed. The runtime is distributed
   as a wheel built for one specific Python minor version, which this root
   filesystem does not carry — hence a container rather than a `pip install`.

   **Run 2026-08-11: everything above the device node worked, and the run
   stopped at the device node** — `RenesasBackendLoad` reported
   `Failed to open device /dev/npuc1`, `driver_open failed: -1`, and ORT raised
   `Create state function failed`. That was the state until the device tree was
   actually tried.

   **Run 2026-08-21: the NPU executes.** Booting the vendor's own NPU device tree
   one-shot from U-Boot — no flash writes, no `saveenv`, so a power cycle
   restores the normal self-boot — brings up `/dev/npuc0`, `/dev/npuc1` and the
   contiguous-memory devices, the backend reports
   `NPUDriverRuntime initialized successfully`, and the shipped ResNet18 sample
   runs **on the NPU**. Three consequences:

   - **The stock bootloader reaches NPU execution, but it is not the configuration
     the vendor documents.** A model runs, which answers the narrow question this
     step was written around. It does not license the broader claim: the AI
     package ships its **own** bootloader, and the manual's appendix describes
     the change as turning DRAM ECC *off*. So Stage 2 is not the performance
     afterthought this document previously called it — it is the documented
     prerequisite, and everything below about model load failing was measured
     without it.
   - **The vendor's NPU device tree omits the realtime core's reserved-memory
     nodes, and the BSP remoteproc driver does not tolerate that.** The service
     that boots the realtime core calls into a prepare hook that uses
     `of_reserved_mem_lookup()` without checking for NULL, so the kernel oopses
     roughly nine seconds into *every* boot of that device tree, before any NPU
     work. Disable that service (and the RPMsg bridge above it) before the
     experiment — losing the realtime core for that boot is already implied by
     the device tree you are booting. `systemd.mask=` on the kernel command
     line did **not** take effect here; `systemctl disable` did.
   - **Loading a model can oops the kernel, on the vendor's own artifacts, with
     the documented prerequisite absent.** On a boot with no prior oops, the
     precompiled yolov5s sample — Renesas-built, single fused subgraph, no
     compiler licence involved — faults with
     `Internal error: Oops - Undefined instruction` during model load; printk
     dies immediately after `Modules linked in:`, RCU stalls follow, and the
     board is unrecoverable without a power cycle. A locally compiled
     7-subgraph model at a larger input size fails the same way. ResNet18, the
     smallest, is the one that works.

     **Do not report this as a vendor defect yet.** Every one of those runs used
     the stock bootloader, i.e. with DRAM ECC on, and the vendor's own appendix
     says the AI package's bootloader turns it off. The vendor's release notes
     also already record timeout-class failures on particular models
     (`OTLINT-22806`, naming HRNet, PointPillars and a YOLOv5 variant), which is
     the same family as the `timeout:reg` lines these runs print. The honest
     order of work is Stage 2 first, then re-measure, then report what survives.

     What can be ruled out cheaply, and was: the runtime's ARC control-core
     firmware is **present** in the board container — the wheel ships its own
     `arc_prog_npu{s,n}` sets, `vpx0.bin` included — so "the control cores were
     never programmed" is not the explanation. Check that before theorising, by
     listing the runtime package inside the container; it needs no board reboot.

   **Where the kernel is loaded matters, and U-Boot's default is wrong for
   this.** The stock load address falls inside one of the NPU's own reserved
   regions, so that region's whole-area contiguous allocation fails with
   `-EBUSY` — visible as one contiguous-memory device missing while the others
   appear, and confirmable in `/proc/iomem`, which shows `Kernel code` inside
   the region. Load the kernel outside every NPU region; read the addresses
   from the SDK's own device tree at the time you do it, and note that U-Boot
   marks every bank above the first as `no-map`, so `ext4load` there fails
   outright with `** Reading file would overwrite reserved memory **`.

   `scripts/npu-probe.sh` is the check to run instead of reading output by eye.
   Without the NPU device tree it stops at layer 2 with
   `NPU_PROBE_FAIL reason=npuc_not_in_dtb sysfs_matches=0 uio_devices=177`,
   which is the correct answer for that configuration.

### Three traps in step 4, all measured

- **The sample script exits 0 when it fails.** `run_inference()` catches every
  exception, prints `Error occurred: ...`, and returns normally. A caller that
  tests `$?` sees success on a board with no NPU at all. Assert on the output
  text.
- **A completed run is not an offloaded run.** The script lists
  `CPUExecutionProvider` after the Renesas EP, so a working-looking latency
  figure is exactly what a board without the NPU would produce if the EP
  declined instead of failing. The provider list from `get_providers()` is the
  minimum assertion; the ORT profiler's per-node assignment
  (`--enable-rtt`) is the real one, and its schema should be read once on
  working hardware before anything asserts against it.
- **The artifacts have to be mounted under their own directory name.** The
  manifest's `artifact_path` is `resnet18_artifacts/nnx/...`, resolved against
  the artifacts directory's *parent*. Mount the directory as
  `/work/artifacts` and the backend looks for `/work/resnet18_artifacts` and
  misses — after printing a path that looks plausible.

### Getting the runtime onto the board

The board has no internet route, no `python3`, and no `tar`; it does have
`podman`, `cpio` and `gzip`. So the image is built elsewhere and moved as a
file, not pulled:

```sh
# on any x86_64 host with qemu binfmt registered
podman build --platform linux/arm64 -t localhost/x5h-ort:1.1.0 .   # python:3.11-slim + the aarch64 wheel
podman save localhost/x5h-ort:1.1.0 | gzip -1 > x5h-ort.tar.gz
ssh root@192.168.0.20 'cat > /root/npu/x5h-ort.tar.gz' < x5h-ort.tar.gz
ssh root@192.168.0.20 'gzip -dc /root/npu/x5h-ort.tar.gz | podman load'
```

Artifacts travel the same way through `cpio -o -H newc | gzip`, unpacked with
`cpio -idm`. Verify both by `sha256sum` on each end rather than by size: a
binary piped through `cat` on the sending side can be silently truncated
(see the transfer note in [selfboot.md](selfboot.md)); stdin redirection as
above is what avoids it. Measured throughput to the bench over the tailnet is
about 1.5 MB/s, so the 164 MB image takes a little under two minutes and the
228 MB artifact archive about two and a half.

Verified on the board: `aarch64`, Python `3.11.15`, `onnxruntime 1.24.0`, and
`get_available_providers()` returning `['RenesasExecutionProvider',
'CPUExecutionProvider']`.

If step 4 passes, the stock IPL is sufficient and Stage 2 is a performance
question to schedule whenever someone is next at the bench. If it fails in a
way that points at the IPL, Stage 2 becomes necessary and its cost is now
known rather than assumed.

## Where this stops

**The appendix that would settle which regions may move is not in this SDK.** It belongs to the separate hardware user's manual. Every document that ships
with the SDK was searched; none marks addresses as redefinable or fixed. Do
not spend an afternoon looking for it here.

**The overlap is not a placement problem.** Compared
against the board's live reserved-memory, the NPU's own allocation map — which
the AI tools carry in their host-application sources, so it can be read
directly rather than inferred — overlaps the bootloader area, the FreeRTOS
application area, the default CMA, and the realtime core's shared window with
the application cores. The last of those is the one that matters: the NPU's
model-binary area does not merely touch that window, it contains it outright,
along with all three of the realtime core's small RAM regions. Carving the
realtime regions back out is therefore not a fix. It would hand the NPU less
memory than it was compiled to address, in the middle of the range it uses.

**There is nowhere below 4 GiB to move to.** That bank is fully spoken for on
this board — bootloader, FreeRTOS application, realtime regions, both CMA
areas — with no gap of any size left over.

**Moving the NPU's regions up is the obvious escape.** The board has ample
free memory above 4 GiB, and the vendor already places half of the NPU's
regions up there, so the hardware plainly reaches it. The compiled model
artifacts do **not** pin the map: they carry no absolute physical addresses in
the affected ranges. Counted against a uniform-noise expectation the NPU
ranges score *below* noise, while a deliberately meaningless control range
scores above it — the apparent matches are quantized weight bytes. A
multi-megabyte weight file "contains" every 32-bit value, so test any pointer
claim against noise before building on it.

What verifiably carries absolute addresses, from reading the tools rather
than pattern-matching binaries: a 44-byte load-map file the compiler frontend
writes next to each compiled model — and the frontend is plain Python with
those constants written into one function, so that file is trivially
regenerable for a different map; the runtime's own region table; and the
device tree. The model binaries show no evidence of baked-in placement. So
relocation looks like a runtime-and-device-tree question, not a
recompile-everything question — but whether the runtime takes its region
table from itself or from the driver is exactly the open vendor question, so
this stays a question rather than a plan.

So the honest summary is that the vendor's NPU configuration and this branch's
realtime work are not, as shipped, configured to coexist — and whether that is
a fixed property of the platform or of this release is not answerable from the
material on hand. That question, and the ones about relocatability and the IPL,
have gone to the vendor. What would unblock the work: confirmation that the NPU
regions may be relocated, and where the runtime takes its region table from.
What would end it differently: confirmation that they may not, in which case
NPU bring-up and the realtime responder become alternative configurations of
this board rather than a single one, and this document needs a different shape.

Separately, the model-compile pipeline itself is no longer a gap: with the
compiler licence in hand, the runtime release's own generation script
reproduces the shipped sample artifacts on the development host — the 44-byte
load map comes out byte-identical — so if relocation does turn out to need
recompilation, the machinery for it is already proven. Two environment potholes
on a current distribution, recorded because both fail after the *frontend*
succeeds: the compiler backend needs two superseded shared libraries the OS no
longer ships, and the frontend *replaces* the library path environment for the
backend subprocess rather than appending to it — so stage those libraries in
the backend's own directory, where its launcher actually looks.

None of this touches Stage 0, the driver build, the udev rules or the runtime
container. All four are done and verified on hardware, and none of them left
the board in a state it was not found in. That is worth stating precisely,
because it narrows the open question to one thing: every layer between the
ONNX model and the device node is now known to work on this board, and what
remains is the device tree — which is exactly what the vendor question is
about.

## Stage 2: the IPL, only if Stage 1 shows it is needed

Two traps, both of which cost real work if hit.

**The vendor's flash procedure overwrites both realtime firmware slots.** Its
write list includes the stock payloads for them, and one of those slots
currently holds this branch's RPMsg responder — measured, not assumed: its
contents differ from the vendor payload in every chunk compared. Running the
procedure unedited breaks the CR52 round trip and therefore
`selfboot-smoke.sh`. Edit the flash-target definition to disable every entry
except the single component being changed.

**Never enable the tool's Linux-files stage.** Alongside the bootloader
entries, the same definition can repartition the storage and write a kernel,
device tree and root filesystem. That is what would destroy the self-boot
partitions. The vendor's own transcript skips it; keep it skipped.

Beyond that, the write itself needs the serial flash writer, two USB-serial
connections, and DIP switch changes, followed by a boot-mode command and a
power cycle.

**It is technically possible to do this from Linux instead.** The flash the
component lives in is exposed as an MTD device, the target offset is
erase-block aligned, and the writable node exists. Do not take that option
for the first attempt: a failed IPL write is recoverable only through the
serial flash writer with physical switch changes, so the one operation whose
failure mode requires someone in the room is the wrong one to do while nobody
is.

## Recovery

- **IPL** — the package ships the stock binary it replaces; write it back the
  same way it was replaced.
- **Realtime firmware slots** — restore from the Stage 0 copies.
- **U-Boot environment** — re-import `selfboot-env.txt` from the boot
  partition ([selfboot.md](selfboot.md)). This needs no host, which is the
  point of it living on the board.
- **A board that will not boot at all** — the serial flash writer, DIP
  switches and a power cycle. This is the floor, and it is why Stage 2 is a
  bench operation.

## What the address space looks like

Worth knowing before touching anything, because it is the reason Stage 1 and
Stage 2 are separable at all:

- The flash tool's storage address space is a small unpartitioned logical
  unit — realtime firmware slots, the secure payloads, U-Boot and the NPU
  firmwares all live there. **It is a different logical unit from the one
  carrying the self-boot partitions**, so writes there cannot reach
  `x5h-boot`, `x5h-root` or `autosd-store`. Address logical units by path and
  by property, never by device letter: the letters move between boots
  ([selfboot.md](selfboot.md)).
- The bootloader components proper live in a separate flash, reachable from
  Linux as an MTD device.

## The AutoSD NPU personality

The board's documented role is the Yocto NPU appliance. AutoSD runs the same NPU
stack on the same hardware, booted one-shot, and it was measured against Yocto on
2026-09-01 across three configurations. **The short answer: AutoSD costs nothing
measurable.** End-to-end latency stayed within 0.7 % of the Yocto baseline in every
configuration, and the accuracy check produced bit-identical numbers in all four.

| Run | Rootfs | Kernel | Runtime | v6 e2e | v7 e2e | vs Yocto |
|---|---|---|---|---|---|---|
| R0 | Yocto | vendor | chroot | 21.429 ms | 21.430 ms | reference |
| R1 | AutoSD | vendor | chroot | 21.084 ms | 21.451 ms | -1.6 % / +0.1 % |
| R2 | AutoSD | `6.1.102-autosd` | chroot | 21.310 ms | 21.287 ms | -0.6 % / -0.7 % |
| R3 | AutoSD | `6.1.102-autosd` | podman | 21.378 ms | 21.328 ms | -0.2 % / -0.5 % |

Twenty runs each, every session reporting
`['RenesasExecutionProvider', 'CPUExecutionProvider']` — a latency figure with only
`CPUExecutionProvider` in that list is void, not a result. R3 minus R2 isolates the
container runtime itself at +0.2 % to +0.3 %, measured on one boot, which is inside
run-to-run noise. Accuracy was `worst_rel = 3.3772e-01` for both candidates in all
four runs, identical to the value the Yocto appliance has produced since 08-26.

All four numbers were measured on the **stock bootloader with DRAM ECC ON**, which is
not the vendor's documented configuration for the AI package. They are mutually
comparable because all four share it; only the absolute values would move if the
bootloader were swapped.

### The one-shot boot, and its three non-negotiables

AutoSD is entered from the U-Boot prompt and nothing is persisted.

- **Never run `saveenv`.** `bootcmd` probes LUN 3, then 2, then 1, so Yocto is what
  an unmodified environment finds first. Every AutoSD boot is therefore one reset away
  from the board's documented role, and that is the entire safety argument for
  operating it remotely. It has been exercised: the board returned to Yocto unaided
  after each AutoSD run.
- **Load the kernel at `0x61080000` and the device tree at `0x61000000`.** Lower
  addresses are stomped and produce an undefined-instruction oops before any console
  output that would explain it.
- **The bootargs must carry all three of the following.** Each was learned by losing a
  session to its absence:
  - `pd_ignore_unused clk_ignore_unused` — without them this BSP gates clocks and power
    domains that are in use, and the SoC stalls at `clk: Disabling unused clocks` with
    no oops, no panic, no watchdog and no SysRq. There is no software recovery.
  - `root=PARTUUID=…`, never `root=PARTLABEL=…` — PARTLABEL is a udev construct, and
    these boots carry no initramfs, so the kernel's `name_to_dev_t()` cannot resolve it.
  - `enforcing=0` — the AutoSD rootfs is `SELINUX=enforcing` but carries no
    `security.selinux` xattrs. This is inert under the vendor kernel, which has no
    SELinux at all, and fatal under `Image-autosd`, which does: enforcing plus fully
    unlabeled locks sshd out with a "Server accepts key" then "Permission denied"
    signature. Confirmed from the other side too — an `Image-autosd` boot logs
    `avc: denied` against `unlabeled_t` with `permissive=1`.

The kernel and the device tree may live on different logical units; the NPU device
tree `r8a78000-ironhide-npu.dtb` is on `x5h-boot` alongside `Image-autosd`. Address
logical units by partlabel, never by device letter — the letters move between boots.

### The safety harness, and what each layer does not catch

Three independent layers, because the failure this guards against is a board that
stops answering with nobody at the bench.

| Layer | Catches | Blind to |
|---|---|---|
| `oops=panic` plus `panic=10` | any oops, including one that leaves PID 1 alive and the box apparently healthy | a wedge that produces no oops |
| systemd hardware watchdog, 30 s pet / 60 s timeout | PID 1 stopping | anything that leaves PID 1 scheduling normally |
| `npu-deadman.timer`, 30 min deadline | a session wedged with the OS still running | a kernel that has stopped scheduling userspace |

`oops=panic` is the load-bearing one. The watchdog fires only if PID 1 stops petting
it, so an oops that leaves systemd alive is invisible to it, and that is precisely the
case that stranded this board before: the vendor remoteproc driver oopses at about
10 s into an AutoSD boot under the NPU device tree, and without `oops=panic` the board
sat there with a live kernel and no route back. Verify `panic_on_oops` reads `1` on
every AutoSD boot before measuring anything. If it reads `0` the kernel ignored the
argument and the session is unprotected.

The deadman is a return-to-safety, not a reset loop: because no `saveenv` was issued,
the reboot it triggers lands on Yocto. Defer it from any long step with
`touch /run/npu-heartbeat`. Its first run self-bootstraps and exits, so it can never
reboot a session that is still starting; with `OnBootSec=10min` the earliest it can
fire is roughly 40 minutes in.

**The harness is proven at the mechanism level only, and this should not be
overstated.** `oops=panic`, `panic=10` and the watchdog arming have all been observed
doing their jobs on real boots. What has never been exercised is a genuine hard
lockup, because one cannot be injected on this board: there is no `lkdtm`
(`/sys/kernel/debug/provoke-crash` is absent), `sysrq` is `16` rather than `1`, and
there are no kernel headers to build a test module with.

**Two panic controls that look obvious are unavailable and must not be added.**
`/proc/sys/kernel/softlockup_panic` and `/proc/sys/kernel/hung_task_panic` do not
exist on this kernel — verified directly, not inferred from a config. Adding
`softlockup_panic=1` or `hung_task_panic=1` to the command line is silently ignored,
so a harness that relies on them protects nothing. `panic_on_rcu_stall` **is**
available and is set via `sysctl.kernel.panic_on_rcu_stall=1`.

The harness itself lives in this repository as
[`config/10-watchdog.conf`](config/10-watchdog.conf),
[`config/npu-deadman.service`](config/npu-deadman.service),
[`config/npu-deadman.timer`](config/npu-deadman.timer) and
[`scripts/npu-deadman.sh`](scripts/npu-deadman.sh). **It is deliberately not wired
into the image manifest.** These are tools for an attended-by-nobody bench session on
a board that is deliberately off its documented role for an hour; a deadman that
reboots on a missing heartbeat is exactly wrong in a shipped image, where no heartbeat
is the normal state. Install them into the target rootfs for the session, and let a
reset take them away with everything else.

### Bringing the NPU up under AutoSD

Most of this is now automatic, from configuration the image already installs
(`x5h-uio.conf`, `51-x5h-uio.rules`, `52-x5h-cmem.rules`). On an `Image-autosd` boot,
`uio_pdrv_genirq` autoloads with its `of_id`, udev creates `/dev/npuc0` and
`/dev/npuc1`, and the runner scripts mount the NPU work partition by partlabel
themselves. An older board image may predate those manifest entries; check
`/etc/udev/rules.d/` and `/etc/modprobe.d/` before assuming the image is current.

**One step is still manual, and it is a real gap rather than an oversight.** `cmemdrv`
is an out-of-tree class driver that lives on the NPU work partition, not in the kernel
module tree, so nothing autoloads it and `systemd-modules-load` reports
`Failed to find module 'cmemdrv'`. It must be loaded by explicit path:

```sh
insmod /opt/npu/cmemdrv.ko      # vermagic must match the running kernel exactly
```

Note that the correct module differs per personality: the copy on the work partition
is built for `6.1.102-autosd` and is the right one when booting `Image-autosd`, but a
boot of the AutoSD rootfs on the *vendor* kernel needs the vendor-kernel build from
the Yocto module tree instead. Closing this properly means the image build installing
a kernel-matched `cmemdrv.ko` into the module tree, which it cannot do today because
the module is not a repository artifact. Until then, a `modules-load.d` entry naming
`cmemdrv` would only log a failure at every boot, so this repository deliberately does
not ship one.

### Two checks that report failure on a perfectly healthy board

Both were written into an earlier revision of the procedure and both are wrong.

- **`grep -c cmem_other /proc/iomem` returns `0` on every kernel**, vendor and AutoSD
  alike, because `/proc/iomem` labels these regions generically as `reserved`. The
  expected count of four is real, but it lives in sysfs: the four entries are class
  devices created by `cmemdrv` when it loads.

  ```sh
  ls /sys/class/cmem/ | grep -c '^cmem_other'   # 4 on a healthy board
  ```

- **`dmesg | grep -ci oops` always matches**, because `oops=panic` on the command line
  matches the harness's own check. The stricter
  `grep -ciE 'Oops:|Unable to handle kernel|Internal error|Call trace'` is better but
  still not safe on Yocto, where the GPU driver emits a benign `WARN_ON` at probe and
  `Call trace:` matches any warning. Judge a boot on
  `Oops:|Unable to handle kernel|Internal error` and treat a `Call trace` hit as
  something to read before believing.

### Running the NPU under podman

The container path reproduces the chroot path exactly, with one correction that costs
an afternoon if missed. `/dev/npuc0` and `/dev/npuc1` are udev **symlinks** to
`uio2`/`uio3`; `--device /dev/npuc0` resolves the symlink and the node appears in the
container under its resolved name, so the backend's literal `open("/dev/npuc1")` fails
with `driver_open failed: -1`. Name the destination explicitly:

```sh
podman run --rm --privileged   --device /dev/uio2:/dev/npuc0 --device /dev/uio3:/dev/npuc1   -v /opt/npu:/npu -w /npu <image>   /usr/local/bin/python3 /npu/renesas_ep_eval_latency.py --artifacts <A> --runs <N>
```

Container storage is btrfs on its own partition, so the `EXT4_FS_SECURITY` gap
recorded elsewhere for this board does not apply to podman here.

## Related

- [UIO](uio.md) — the mechanism `/dev/npuc*` arrives through, and the drop-in
  that enables it.
- [CR52 slot update](cr52-slot-update.md) — the established procedure for
  writing that logical unit from Linux, and the slots Stage 2 must not touch.
- [UFS self-boot](selfboot.md) — the partition layout Stage 2 must not
  disturb, and the environment-restore path.
