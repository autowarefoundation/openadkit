# X5H NPU: the host-side inputs and the board-side checks

What lives here is the part of NPU work that can live in a public repository:
the scripts that turn public model weights into compiler inputs, and the checks
that grade what the board does with the result. The procedure, the reasoning and
the recovery paths are in [../npu-bringup.md](../npu-bringup.md); read that
first if you are about to touch the board.

**Read the status section of that document before quoting any of this as
working.** As of 2026-08-26 the full three-branch VisionPilot pipeline runs on
the NPU as a single fused subgraph, with no compute nodes left on the CPU. The
model-load kernel fault reported here on 2026-08-21 is resolved and was not a
model-size limit: the kernel had been loaded at an address the NPU runtime
later writes over, which nothing in the runtime validates or reports. Load the
kernel where the vendor documents and it does not occur.

## What is not here, and why

The compiler wrapper, the licence, the SDK paths and every vendor address stay
outside this repository, exactly as in
[../cr52-slot-update.md](../cr52-slot-update.md). That is not tidiness: the SDK
is NDA-bound material. The scripts here take file paths as arguments and read
vendor values from the SDK at the time you run them, so nothing needs to be
copied in to make them work.

Concretely, the NNAC compile step itself — `renesas_ep_gen_artifacts.py` from
the runtime release, plus a local wrapper for the model that needs post-legalize
surgery — is invoked from the working area, not from here.

## Host: from public weights to compiler inputs

| Step | Script | Marker |
| --- | --- | --- |
| Fetch the pinned VisionPilot models | `vp-models/export-models.sh [dest] [src]` | `VP_MODELS_OK` |
| Pin the symbolic batch dimension | `vp-models/fix-static-shapes.py <src> <dst>` | `STATIC_SHAPES_OK` |
| Build calibration data and replay feeds | `vp-models/calib-dump.py --model … --clip …` | `CALIB_DUMP_OK` |

Order matters for the middle one: the models ship with a symbolic batch
dimension on inputs *and* outputs, and the compiler frontend fails late, inside
legalization, if it is left symbolic. Pinning the inputs alone is not enough.

`calib-dump.py` mirrors the pinned VisionPilot C++ preprocessing rather than a
reasonable-looking reconstruction of it, because the three models are **not**
preprocessed the same way — one gets a perspective-warped image with ImageNet
normalization, the other two share a top-cropped resize with no normalization
beyond `/255`. Feeding either model the other's tensors sets every quantization
range wrong at once. Two of the model headers also document preprocessing the
code does not perform; the code is what runs. The constants and their source
lines are in the script's docstring.

It writes two trees from one pass: a calibration tree in the layout
`--calibration-path` expects (one directory per input, file names sorting into
frame order, equal counts per input — the generator indexes inputs by position),
and an ordered replay tree for the consistency check.

## Board: grading what actually happened

| Step | Script | Marker |
| --- | --- | --- |
| Prove the whole chain to the device node | `../scripts/npu-probe.sh [artifacts] [image]` | `NPU_PROBE_PASS` / `NPU_PROBE_FAIL reason=…` |
| Compare NPU against CPU over replay feeds | `vp-models/consistency-check.py` | `CONSISTENCY_PASS` / `_FAIL` / `_CALIBRATED` |

Run the probe first, and grade by its marker rather than by an exit status or by
reading output. Three reasons, all measured rather than assumed:

- The vendor's evaluation script catches every exception, prints
  `Error occurred: …` and returns normally, so `$?` is 0 on a board with no NPU
  at all.
- A completed run is not an offloaded run: the provider list ends in
  `CPUExecutionProvider`, so a board without a working NPU produces correct
  results and a plausible latency.
- A run can print correct numbers on a kernel that has **already** oopsed. The
  probe refuses to measure on a damaged kernel and checks again afterwards;
  nothing else in this directory does.

`consistency-check.py` freezes an envelope rather than demanding equality — the
NPU path is quantized, so it cannot match the CPU exactly, and the useful
question is whether the difference has moved. Calibrate once per model
(`--calibrate`), commit the resulting `tolerance.json`, then run without the
flag to assert. Calibration merges into the existing file, so calibrating the
second model does not evict the first.

`tolerance.json` is **not** committed. The envelope is only meaningful once
frozen against the model and board configuration it will be asserted on, so
generate it with `--calibrate` for the model you are shipping rather than
inheriting one from a different build.

## Two findings that decide how a model is compiled and where it is decoded

Neither is discoverable from the compiler output, and both cost real time, so
they are written down here rather than left in a working area.

**Sweep `--slice`; do not assume more is better.** The flag sets how many NPX
slices execute the network, and the useful value is a property of the model,
not of the board. Measured on the merged three-branch model at 1024x512: the
best end-to-end time came from **3 of the 12 available slices**, and using all
twelve was *worse than using one*. Two effects compose to produce that. The
NPU-side compute stops improving once the network runs out of work to divide —
past four slices it was flat to within 0.01 ms, which is what a 16x32
bottleneck feature map should be expected to do — while dispatch and
synchronisation cost about a millisecond per slice and simply keep
accumulating. The sum therefore has a minimum in the middle. Sweep the values
for the model in hand; the optimum moves with input resolution and batch size,
so it has to be re-checked after any re-export rather than carried over.

**Decode softmax-family heads on the host, not on the NPU.** A softmax output
is quantized on a fixed [0,1] grid, so the per-position rounding of a
soft-argmax head — softmax over positions, then a position-weighted
expectation, the usual shape for lane offsets and for DFL box decoding — lands
differently from frame to frame and shows up as a visibly jittering output on
otherwise smooth input. No weight rescaling can fix it, because nothing changes
a softmax's output range. Cutting the graph at the pre-softmax logits and doing
softmax plus expectation on the host in float restored the jitter to the float
reference exactly, for no measurable latency cost — the tensor crossing the
boundary is small, and the arithmetic leaves the NPU with it.

## Mounting artifacts, which is the trap that looks like a driver bug

The backend opens the artifact path recorded in the manifest. The shipped
samples record a path *relative* to the artifacts directory's parent and
starting with that directory's own name, so the mount must preserve the
directory name — mount it as `/work/artifacts` and the backend looks for
`/work/<name>` and misses. Locally compiled artifacts instead record the
*absolute* path of the machine that compiled them, which the backend opens
verbatim, so there the mount point has to be that path. `npu-probe.sh` reads the
manifest and picks the right form; do the same by hand.
