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
> a vendor defect in its own right. They are now offered as two switchable boot
> roles on the same board rather than as two boards: `npu` and `cr52`, one per
> boot, described in [selfboot.md](selfboot.md), "Roles". The earlier practice
> of keeping NPU verification on a separate board is withdrawn, along with the
> 2026-08-25 invariant that board 1 carries no NPU boot path.
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
can also be restored from `x5h-env.txt` and `x5h-role.txt` on the boot partition
with no host at all ([selfboot.md](selfboot.md)), so that remains belt and
braces.

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
     line did **not** take effect here; `systemctl disable` did. On an image
     built from this branch neither is needed by hand: `cr52-remoteproc.service`
     and `rpmsg-eth.service` both carry
     `ConditionKernelCommandLine=x5h.role=cr52`, so a boot in the `npu` role
     skips them, and that condition is what the design relies on precisely
     because `systemd.mask=` was measured not to work.
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

## The container contract (npu role)

Everything above is about making the NPU reachable. This section is the
handoff: what a board booted in the `npu` role guarantees to a container, in
the exact form the board itself asserts it. `scripts/npu-contract-smoke.sh`
ships in the image at `/usr/sbin/npu-contract-smoke.sh` and is the executable
copy of this contract; if the two ever disagree, the script is right.

The prerequisite is the role's own bring-up unit. `x5h-npu.service` carries
`ConditionKernelCommandLine=x5h.role=npu`, requires `var-opt-npu.mount` (the
unit is named for `/var/opt/npu` because `/opt` is a symlink to `var/opt` on
this rootfs), inserts `cmemdrv.ko` from `npu-work`, waits for the device nodes
and logs `NPU_READY uio=<n> cmem=<n>`. Until that marker is in the journal
there is no contract to hand anyone, and `npu-contract-smoke.sh` refuses to run
with `NPU_CONTRACT_FAIL reason=npu_not_ready`.

The image is built on the board, from the vendor `ort-rootfs` tree that lives
on `npu-work` and never in this repository:

```sh
podman build -t localhost/x5h-ort-rootfs:latest \
  -f /usr/sbin/ort-rootfs.containerfile \
  --ignorefile /usr/sbin/ort-rootfs.containerignore /opt/npu/ort-rootfs
```

The ignore file is not optional: `ort-rootfs/npu` is the bind target of
`/opt/npu`, which contains `ort-rootfs` itself, so a build without it recurses
forever. `tar | podman import` is not an alternative, because the AutoSD image
ships no `tar`.

The run is the contract proper:

```sh
podman run --rm --privileged \
  --device /dev/uio2:/dev/npuc0 --device /dev/uio3:/dev/npuc1 \
  --device /dev/cmem0 --device /dev/cmem_other0 --device /dev/cmem_other1 \
  --device /dev/cmem_other2 --device /dev/cmem_other3 \
  -v /opt/npu:/npu -w /npu localhost/x5h-ort-rootfs:latest \
  /usr/local/bin/python3 /npu/renesas_ep_eval_latency.py \
    --artifacts /npu/<artifact-set> --runs 20
```

Three details in that command are load-bearing:

- **The `uioN:npucN` destinations must be spelled out.** `npuc0` and `npuc1`
  are udev symlinks, so `--device /dev/npuc0` resolves on the host and podman
  creates the node inside the container under its resolved name, `uio2`. The
  backend then calls `open("/dev/npuc1")` literally and fails. Naming the
  destination is what makes the container see the names the runtime expects.
- **`/opt/npu` is mounted at `/npu`, not somewhere convenient.** Artifact sets
  are addressed relative to it, and compiled artifacts also record absolute
  compile-host paths, so the mount point is part of the contract rather than a
  preference.
- **`cmem_other0` through `cmem_other3`, all four.** Their count comes from the
  `/cmem` node's phandle list, so a missing one is a device-tree fault and not
  something the container can work around. `x5h-npu.service` already refuses to
  reach `NPU_READY` unless four exist.

Grade the run by output, never by exit status: `renesas_ep_eval_latency.py`
catches every exception and still exits 0 (see "Three traps in step 4"). The
smoke script prints `NPU_CONTRACT_PASS avg_ms=<v> runs=<n> image=<ref>` only
when the session listed `RenesasExecutionProvider` and a latency figure could
be parsed, and otherwise `NPU_CONTRACT_FAIL reason=<wrong_role|npu_not_ready|
no_image|no_artifacts|no_renesas_ep|no_latency|bad_args>`.

**Switching away from this role is a full SoC reset, and it reloads the CR52.**
`x5h-role set cr52 --reboot` is not a userspace handover: a warm reboot on this
board is a PSCI cold reset, so the realtime core restarts and re-reads its
flashed payload. That is the mechanism that makes the two roles safe to
alternate at all, because in the `npu` role the CR52's shared window and its
three small RAM regions lie inside the NPU's model-binary region and must be
assumed overwritten. Nothing has to be done by hand to repair it; equally,
nothing short of that reset repairs it, so do not expect a role switch without
a reboot to work.

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
procedure unedited breaks the CR52 round trip, and therefore the `cr52` role:
`rpmsg-eth-smoke.sh` is the check that goes red. Edit the flash-target
definition to disable every entry except the single component being changed.

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
- **U-Boot environment**: re-import `x5h-env.txt` from the boot partition,
  and check `x5h-role.txt` beside it ([selfboot.md](selfboot.md)). This needs
  no host, which is the point of both files living on the board. A missing or
  unreadable role file is not fatal on its own: U-Boot falls back to the `npu`
  role.
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

## Related

- [UIO](uio.md) — the mechanism `/dev/npuc*` arrives through, and the drop-in
  that enables it.
- [CR52 slot update](cr52-slot-update.md) — the established procedure for
  writing that logical unit from Linux, and the slots Stage 2 must not touch.
- [UFS self-boot](selfboot.md) — the partition layout Stage 2 must not
  disturb, and the environment-restore path.
