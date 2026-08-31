#!/usr/bin/env python3
"""Compare CPU-only against NPU-offloaded outputs over ordered replay feeds.

Runs ON THE BOARD, inside the runtime container, so that both sessions see
byte-identical inputs from the same files. Two modes:

  --calibrate  record the observed per-output envelope into the tolerance file
  default      assert every frame stays inside the frozen envelope

The point is not that the NPU matches the CPU exactly -- it cannot, the NPU
path is quantized -- but that the difference stays where it was when someone
last looked at it. That is why the tolerances are frozen in git rather than
computed at assert time.

Two things this deliberately does not do:

* It does not trust a completed run. The Renesas provider lists
  CPUExecutionProvider as a fallback, so a board with no working NPU produces
  correct results and a plausible latency; the provider list is asserted here,
  and `scripts/npu-probe.sh` is what checks the layers underneath.
* It does not check the kernel. A run can print correct numbers on a kernel
  that has already oopsed (measured 2026-08-21), so run npu-probe.sh -- which
  refuses a damaged kernel -- rather than reading a PASS here as "the board is
  healthy".

Mounting: the backend resolves the artifact path recorded in the manifest, which
is relative for the shipped samples and absolute for locally compiled models.
Mount the artifacts at the recorded path, not under a parent of your choosing;
npu-probe.sh reads the manifest and does this correctly.
"""
import argparse
import glob
import json
import pathlib
import sys

import numpy as np
import onnxruntime as ort

EP = "RenesasExecutionProvider"


def cosine(a, b):
    a, b = a.ravel().astype(np.float64), b.ravel().astype(np.float64)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return 1.0 if denom == 0 else float(np.dot(a, b) / denom)


def pick_model(artifacts):
    """The compiled model to run, preferring the QDQ-inserted one.

    That is the model the compile pipeline actually produces artifacts for, and
    on a board copy trimmed for size it is often the only ONNX file present --
    so globbing `legalized_*` alone finds nothing and fails late.
    """
    for pattern in ("qdq_inserted_legalized_*.onnx", "legalized_*.onnx", "*.onnx"):
        hits = sorted(glob.glob(str(pathlib.Path(artifacts) / pattern)))
        if hits:
            return hits[0]
    sys.exit(f"CONSISTENCY_FAIL reason=no_model_in_artifacts path={artifacts}")


def load_feeds(feeds):
    frames = sorted(pathlib.Path(feeds).glob("frame*"))
    if not frames:
        sys.exit(f"CONSISTENCY_FAIL reason=no_feeds path={feeds}")
    return frames


def freeze_tolerance(tol_path, name, stats, headroom):
    """Write this model's envelope into the tolerance file, keeping the others.

    Each model is calibrated in its own run, so a write that replaced the file
    would evict whatever was frozen before it -- the failure mode is silent,
    and it looks like the earlier model was never calibrated.
    """
    existing = {}
    if tol_path.exists():
        try:
            existing = json.loads(tol_path.read_text())
        except json.JSONDecodeError:
            sys.exit(f"CONSISTENCY_FAIL reason=tolerance_unparseable path={tol_path}")
    existing[name] = {
        k: {"max_abs_diff": v["max_abs_diff"] * headroom,
            "min_cosine": max(0.0, 1 - (1 - v["min_cosine"]) * headroom)}
        for k, v in stats.items()
    }
    tol_path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    return existing


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--feeds", required=True, help="dir of frameNNNN/<input>.npy")
    ap.add_argument("--tolerance", required=True)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--headroom", type=float, default=1.2,
                    help="factor applied to the observed envelope when freezing")
    a = ap.parse_args()

    model = pick_model(a.artifacts)
    name = pathlib.Path(a.artifacts).name.removesuffix("_artifacts")

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    s_npu = ort.InferenceSession(model, so, providers=[EP, "CPUExecutionProvider"])
    if EP not in s_npu.get_providers():
        sys.exit(f"CONSISTENCY_FAIL reason=silent_cpu_fallback providers={s_npu.get_providers()}")
    s_cpu = ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])
    out_names = [o.name for o in s_cpu.get_outputs()]

    stats = {}
    frames = load_feeds(a.feeds)
    for frame_dir in frames:
        feed = {p.stem: np.load(p) for p in sorted(frame_dir.glob("*.npy"))}
        npu_out, cpu_out = s_npu.run(None, feed), s_cpu.run(None, feed)
        for out_name, npu_t, cpu_t in zip(out_names, npu_out, cpu_out):
            diff = float(np.max(np.abs(npu_t.astype(np.float64) - cpu_t.astype(np.float64))))
            st = stats.setdefault(out_name, {"max_abs_diff": 0.0, "min_cosine": 1.0})
            st["max_abs_diff"] = max(st["max_abs_diff"], diff)
            st["min_cosine"] = min(st["min_cosine"], cosine(npu_t, cpu_t))

    tol_path = pathlib.Path(a.tolerance)

    if a.calibrate:
        freeze_tolerance(tol_path, name, stats, a.headroom)
        print(json.dumps({name: stats}, indent=2, sort_keys=True))
        print(f"CONSISTENCY_CALIBRATED model={name} frames={len(frames)} headroom={a.headroom}")
        return

    if not tol_path.exists():
        sys.exit(f"CONSISTENCY_FAIL reason=tolerance_missing path={tol_path}")
    frozen = json.loads(tol_path.read_text()).get(name)
    if not frozen:
        sys.exit(f"CONSISTENCY_FAIL reason=model_not_in_tolerance model={name} path={tol_path}")

    failed = False
    for out_name, v in sorted(stats.items()):
        limit = frozen.get(out_name)
        if limit is None:
            print(f"CONSISTENCY_FAIL model={name} output={out_name} reason=output_not_in_tolerance")
            failed = True
            continue
        if v["max_abs_diff"] > limit["max_abs_diff"] or v["min_cosine"] < limit["min_cosine"]:
            print(f"CONSISTENCY_FAIL model={name} output={out_name} observed={v} limit={limit}")
            failed = True
    if failed:
        sys.exit(1)
    print(f"CONSISTENCY_PASS model={name} frames={len(frames)} outputs={len(stats)}")


if __name__ == "__main__":
    main()
