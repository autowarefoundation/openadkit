#!/usr/bin/env python3
"""Assert a VisionPilot smoke log: frame count + numeric consistency.

VisionPilot logs one line per *planned* frame to stdout, e.g.:

  [INFO]  plan: tyre=0.2247 rad  accel=1.015 m/s²  |  cte=-0.17m(raw=-0.20m)  |  cipo=true  dist=37.8 m  vel=+1.56 m/s

We parse those "plan:" lines. The count is the number of frames that produced a
plan: an N-frame clip yields N-1 planned frames, because the AutoDrive model
consumes the first frame as temporal history (image_prev + image_curr). The six
floats on each line (tyre, accel, cte, raw_cte, dist, vel) are the per-frame
numeric outputs; they are compared against a reference within a calibrated
absolute tolerance. The interleaved "Latency" lines are wall-clock timing
(non-deterministic across runs/arches) and are deliberately ignored.

Modes:
  Extract:   assert-smoke.py --log run.log --expect-frames 99 --dump out.json
  Compare:   assert-smoke.py --log run.log --expect-frames 99 \
                 --reference reference-amd64.json --tolerance tolerance.json
  Calibrate: assert-smoke.py --calibrate a.json b.json --out tolerance.json
"""
import argparse, json, re, sys

PLAN_RE = re.compile(r"\bplan:\s")          # marks a per-frame plan line
NUM_RE = re.compile(r"[-+]?\d+\.\d+")       # the six floats on a plan line


def extract(path, dedup=False):
    frames = []
    for line in open(path, errors="replace"):
        if not PLAN_RE.search(line):
            continue
        vals = [float(v) for v in NUM_RE.findall(line)]
        # podman+systemd can journal each container line twice (its journald log
        # driver and the unit's stdout capture), so the serial journal shows each
        # plan line as an identical adjacent pair. Collapse exact-equal adjacent
        # tuples; real consecutive frames always differ (tyre is logged to 4 dp).
        if dedup and frames and frames[-1]["values"] == vals:
            continue
        frames.append({"frame": len(frames), "values": vals})
    return frames


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--log")
    p.add_argument("--expect-frames", type=int)
    p.add_argument("--reference")
    p.add_argument("--tolerance")
    p.add_argument("--dump")
    p.add_argument("--calibrate", nargs=2)
    p.add_argument("--out")
    p.add_argument("--dedup-consecutive", action="store_true",
                   help="collapse identical adjacent plan lines (journald double-logging)")
    a = p.parse_args()

    # Usage validation (fail with a clear message, not a stack trace).
    if not a.calibrate and not a.log:
        sys.exit("usage: give --log (extract/compare) or --calibrate a.json b.json")
    if a.reference and not a.tolerance:
        sys.exit("--reference requires --tolerance")
    # Compare mode without a frame-count floor would silently PASS a run that
    # crashed before emitting any 'plan:' line (zip truncates to the shorter
    # list), so require the count guard whenever comparing to a reference.
    if a.reference and a.expect_frames is None:
        sys.exit("--reference requires --expect-frames (guards against a short/empty run)")

    if a.calibrate:
        runs = [json.load(open(f)) for f in a.calibrate]
        # Per-field tolerance: fields span very different scales (tyre ~0.2 rad
        # vs dist ~16-40 m) and variances, so a single global tolerance would be
        # dominated by the noisiest field and leave the small ones unchecked.
        nfields = max((len(f["values"]) for f in runs[0]), default=0)
        maxd = [0.0] * nfields
        for fa, fb in zip(runs[0], runs[1]):
            for i, (x, y) in enumerate(zip(fa["values"], fb["values"])):
                maxd[i] = max(maxd[i], abs(x - y))
        # Floor at 0.05: the plan log prints these fields with 1-4 decimals
        # (dist to 0.1, cte/vel to 0.01), so a tolerance below the print
        # quantization would demand near-exact matches and spuriously fail on a
        # different machine/arch — contrary to "bit-exactness not required".
        tol = {"abs_tol_per_field": [max(4 * d, 0.05) for d in maxd]}
        json.dump(tol, open(a.out, "w"), indent=2)
        print(f"calibrated {tol}")
        return

    frames = extract(a.log, dedup=a.dedup_consecutive)
    n = len(frames)
    if a.expect_frames is not None and n < a.expect_frames:
        sys.exit(f"FAIL: {n} plan frames logged, expected >= {a.expect_frames}")
    if a.dump:
        json.dump(frames, open(a.dump, "w"), indent=2)
    if a.reference:
        ref = json.load(open(a.reference))
        tol = json.load(open(a.tolerance))["abs_tol_per_field"]
        for got, want in zip(frames, ref):
            if len(got["values"]) != len(want["values"]):
                sys.exit(f"FAIL: frame {got['frame']}: {len(got['values'])} values "
                         f"vs {len(want['values'])} in reference")
            for i, (x, y) in enumerate(zip(got["values"], want["values"])):
                if abs(x - y) > tol[i]:
                    sys.exit(f"FAIL: frame {got['frame']} field {i}: {x} vs {y} (tol {tol[i]})")
        print(f"PASS: {n} frames (compared against reference, per-field tol {tol})")
        return
    print(f"PASS: {n} frames")


if __name__ == "__main__":
    main()
