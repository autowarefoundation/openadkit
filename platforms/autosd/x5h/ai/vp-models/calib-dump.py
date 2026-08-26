#!/usr/bin/env python3
"""Dump NNAC calibration data and ordered replay feeds for the VisionPilot models.

Fidelity is the whole point: calibration is only as good as its agreement with
what the vehicle actually feeds the model, and a plausible-looking
normalization VisionPilot does not use produces quantization ranges that are
wrong everywhere at once. Everything below mirrors the pinned VP C++ pipeline
(commit bdbfc32), which does NOT preprocess uniformly -- it builds two
different images per frame:

  autodrive            <- BEV cv::warpPerspective(C, 1024x512, INTER_LINEAR,
                          BORDER_REFLECT_101), BGR->RGB, /255, then ImageNet
                          mean/std. Two inputs: the previous and current
                          warped frame.
  autosteer, autospeed <- top-crop to 2:1 then cv::resize to 1024x512
                          (INTER_LINEAR), BGR->RGB, /255 and nothing else.
                          They share one buffer, so one input each.

    modules/sensing/image_preprocessing/src/image_preprocessor.cpp:10-22
    modules/models/src/inference.cpp:18-54 (chw_imagenet / chw_01), 141-175
    modules/common/include/common/utils.hpp:15-19 (the crop rule)

Two headers document preprocessing the code does not do -- auto_speed.hpp
claims a (114,114,114) letterbox, auto_drive.hpp says "resize" where the code
warps. The code wins; do not restore either from the comments.

C is derived here from the dataset ground homography, the same way
VisionPilot/scripts/find_homography_C_matrix.py derives it, because the
generated C yaml is gitignored in VP and so cannot be depended on. Note the
shipped H.yaml is annotated for OpenLane 1920x1080 pixel space while the pinned
smoke clip is 1920x1280: this is VP's own default calibration applied to the
clip, not a per-clip calibration, and it shifts the BEV geometry. It does not
shift the pixel statistics that set quantization ranges, which is what this
dump is for.

Two trees come out of one pass, from the same tensors:
  <calib-out>/<model>/<input_name>/fNNNN.npy      what --calibration-path wants
  <feeds-out>/<model>/frameNNNN/<input_name>.npy  ordered, for the consistency check

The calibration layout is not a convention we chose: renesas_ep_utils.
generate_calibration() globs <calibration-path>/<input_name>/*.npy, sorts it,
and indexes every input by position -- so per-input file counts must match and
the names must sort into frame order.

DO NOT MERGE TWO OF THESE TREES BY COPYING DIRECTORIES TOGETHER. Each run
starts at the first frame that model can actually be fed -- t=1 for a model
that takes a history frame, t=0 for one that does not (see `start` below) --
so sample i means a different source frame in the two trees. Concatenating
them for a merged multi-branch model therefore feeds one branch frame i and
another frame i+1, silently: every file is present, the counts match, the
generator is happy, and nothing anywhere reports a skew. Measured in 2026-08,
where it put a one-frame lag into a merged model's inputs and into every
overlay rendered from them.

To build calibration for a merged model, dump it in one pass against the
merged model itself, so a single `start` governs all of its inputs.
"""
import argparse
import pathlib
import sys

import cv2
import numpy as np

NET_W, NET_H = 1024, 512
# ImageNet constants, applied after the /255 (inference.cpp:22-23).
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
# VisionPilot's fixed model-view homography (1024x512 pixel -> world), copied
# verbatim from scripts/find_homography_C_matrix.py, where it is marked
# "DO NOT MODIFY".
V = np.array(
    [
        [0.00209514907, -0.000941721466, -9.24906396],
        [0.00662758637, -0.000352940531, -3.33396502],
        [0.000120077371, -0.00411343505, 1.0],
    ],
    dtype=np.float32,
)
CANONICAL_WORLD_PTS = np.array(
    [[15, 5, 1], [150, 5, 1], [15, -5, 1], [150, -5, 1]], dtype=np.float32
)

# How each model is fed. "bev" and "crop" name the geometric stage; "imagenet"
# selects the normalization. history=True means the model also takes frame t-1,
# which is why its first usable sample is t=1.
PREPROC = {
    "autodrive": dict(geom="bev", imagenet=True, history=True),
    "autosteer": dict(geom="crop", imagenet=False, history=False),
    "autospeed": dict(geom="crop", imagenet=False, history=False),
}


def find_c_matrix(h_yaml):
    """Rebuild VP's preprocess homography C from the dataset ground H."""
    fs = cv2.FileStorage(str(h_yaml), cv2.FILE_STORAGE_READ)
    h = fs.getNode("H").mat()
    fs.release()
    if h is None:
        sys.exit(f"CALIB_DUMP_FAIL no H matrix in {h_yaml}")
    uv = np.linalg.inv(h) @ CANONICAL_WORLD_PTS.T
    pq = np.linalg.inv(V) @ CANONICAL_WORLD_PTS.T
    c, _ = cv2.findHomography((uv[:2] / uv[2]).T, (pq[:2] / pq[2]).T, method=0)
    return c


def geom_bev(frame_bgr, c):
    return cv2.warpPerspective(frame_bgr, c, (NET_W, NET_H), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REFLECT_101)


def geom_crop(frame_bgr):
    """Top-crop to 2:1, then resize -- utils.hpp compute_top_crop_2_1."""
    h, w = frame_bgr.shape[:2]
    crop_top = max(0, int(round(h - w / 2.0)))
    return cv2.resize(frame_bgr[crop_top:, :], (NET_W, NET_H), interpolation=cv2.INTER_LINEAR)


def tensorize(img_bgr, imagenet):
    """BGR uint8 -> NCHW float32, /255, optionally ImageNet-normalized."""
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    if imagenet:
        rgb = (rgb - MEAN) / STD
    return np.ascontiguousarray(np.transpose(rgb, (2, 0, 1))[None])


def decode(clip, max_frames):
    cap = cv2.VideoCapture(str(clip))
    frames = []
    while len(frames) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="model .onnx (names the preprocessing)")
    ap.add_argument("--clip", required=True)
    ap.add_argument("--calib-out", required=True)
    ap.add_argument("--feeds-out", required=True)
    ap.add_argument("--ground-h", default="/tmp/vp-src/VisionPilot/config/H.yaml",
                    help="dataset ground homography H (VP config/H.yaml)")
    ap.add_argument("--max-frames", type=int, default=100)
    a = ap.parse_args()

    name = pathlib.Path(a.model).stem
    key = name.split("_")[0]
    if key not in PREPROC:
        sys.exit(f"CALIB_DUMP_FAIL unknown model {name} (expected one of {sorted(PREPROC)})")
    cfg = PREPROC[key]

    import onnxruntime as ort  # after arg parsing: a bad path should fail fast

    sess = ort.InferenceSession(a.model, providers=["CPUExecutionProvider"])
    inputs = [i.name for i in sess.get_inputs()]
    if cfg["history"] != (len(inputs) > 1):
        sys.exit(f"CALIB_DUMP_FAIL {name} has inputs {inputs}, "
                 f"which contradicts history={cfg['history']}")

    frames = decode(a.clip, a.max_frames)
    if len(frames) < 2:
        sys.exit(f"CALIB_DUMP_FAIL decoded {len(frames)} frames from {a.clip}")

    c = find_c_matrix(a.ground_h) if cfg["geom"] == "bev" else None
    prepared = [geom_bev(f, c) if cfg["geom"] == "bev" else geom_crop(f) for f in frames]
    tensors = [tensorize(img, cfg["imagenet"]) for img in prepared]

    # VP holds a one-deep frame buffer and returns no inference for the first
    # frame (inference.cpp:141-148), so the two-input model's first real sample
    # is t=1 with prev=t0. Starting at t=0 with prev==curr would feed the
    # calibration a zero-motion frame pair the vehicle never produces.
    #
    # This is per-model correct and cross-model INCOMPARABLE: sample i is
    # source frame i+start, and start differs between models here. See the
    # merge warning in the module docstring before combining two output trees.
    start = 1 if cfg["history"] else 0
    calib_root = pathlib.Path(a.calib_out) / name
    feeds_root = pathlib.Path(a.feeds_out) / name
    for idx, t in enumerate(range(start, len(tensors))):
        feed = {}
        for input_name in inputs:
            feed[input_name] = tensors[t - 1] if "prev" in input_name else tensors[t]
        frame_dir = feeds_root / f"frame{idx:04d}"
        frame_dir.mkdir(parents=True, exist_ok=True)
        for input_name, tensor in feed.items():
            np.save(frame_dir / f"{input_name}.npy", tensor)
            calib_dir = calib_root / input_name
            calib_dir.mkdir(parents=True, exist_ok=True)
            np.save(calib_dir / f"f{idx:04d}.npy", tensor)

    samples = len(tensors) - start
    stats = np.concatenate([t.ravel()[::997] for t in tensors])
    print(f"  inputs={inputs} geom={cfg['geom']} imagenet={cfg['imagenet']} "
          f"range=[{stats.min():.3f},{stats.max():.3f}] mean={stats.mean():.3f}")
    print(f"CALIB_DUMP_OK model={name} samples={samples} frames={len(frames)}")


if __name__ == "__main__":
    main()
