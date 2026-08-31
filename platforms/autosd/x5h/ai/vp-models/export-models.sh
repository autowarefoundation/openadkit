#!/usr/bin/env bash
# Fetch the VisionPilot commit pinned by fork PR #10 and extract the runtime
# ONNX models (weights are regular files at that commit).
#
# The plan expected two models named EgoLanes_FP32/AutoSteer_FP32; at this pin
# the pipeline is three models -- inference.cpp loads
# "auto{drive,steer,speed}_<precision>.onnx" and vision_pilot.conf sets
# model.precision = fp32 -- so those three fp32 files are what "the models
# VisionPilot runs" means here.
#
# The extracted models declare a symbolic batch dimension, which the NNAC
# frontend cannot compile. Pin it with fix-static-shapes.py (needs the host
# venv's onnx) before compiling anything from them.
set -euo pipefail
VP_REPO=https://github.com/autowarefoundation/autoware_vision_pilot.git
VP_COMMIT=bdbfc328b822f9820d0dc14a7979beb4dfb8f3a9
DEST="${1:-/tmp/vp-models}"
SRC="${2:-/tmp/vp-src}"
# Both paths are resolved here, before anything uses them, and nothing below
# changes directory (every git call is `git -C`). Otherwise a relative DEST or
# SRC would mean one thing on a cold checkout -- resolved against $SRC, which
# the clone had cd'd into -- and another when $SRC was already populated,
# writing the models to two different places for the same arguments. The
# defaults are absolute, which hides this rather than preventing it.
mkdir -p "$SRC" "$DEST"
SRC=$(cd "$SRC" && pwd)
DEST=$(cd "$DEST" && pwd)
if [ ! -d "$SRC/.git" ]; then
  git -C "$SRC" init -q
fi
if git -C "$SRC" remote get-url origin >/dev/null 2>&1; then
  git -C "$SRC" remote set-url origin "$VP_REPO"
else
  git -C "$SRC" remote add origin "$VP_REPO"
fi
# $SRC is a cache only while it holds the PINNED commit. An existing
# $SRC/.git was previously taken as proof of that and the fetch/checkout was
# skipped outright -- so a tree left at any other commit (the default
# /tmp/vp-src persists across runs, and this repository's history moves) was
# accepted silently: the three model basenames below exist at more than one
# commit, so all three would be found, copied, and reported VP_MODELS_OK
# while being off-pin. Checking HEAD rather than the directory keeps the
# cache but makes the pin the thing that decides.
if [ "$(git -C "$SRC" rev-parse -q --verify HEAD 2>/dev/null || true)" != "$VP_COMMIT" ]; then
  git -C "$SRC" fetch -q --depth 1 origin "$VP_COMMIT"
  git -C "$SRC" checkout -q FETCH_HEAD
fi
# Post-condition, not belt-and-braces: `checkout FETCH_HEAD` after a
# --depth 1 fetch of an explicit SHA can only land on that SHA, so a
# mismatch here means the assumption itself broke (a server resolving the
# ref differently, a fetch that no-op'd). Fail loudly rather than export
# models from an unknown tree.
head=$(git -C "$SRC" rev-parse HEAD)
[ "$head" = "$VP_COMMIT" ] \
  || { echo "VP_MODELS_FAIL src_head=$head (expected $VP_COMMIT)"; exit 1; }
found=0
while IFS= read -r f; do
  case "$(basename "$f")" in
    autodrive_fp32.onnx|autosteer_fp32.onnx|autospeed_fp32.onnx) cp "$f" "$DEST/"; found=$((found+1));;
  esac
done < <(find "$SRC" -name '*.onnx' -not -path '*/.git/*')
[ "$found" -eq 3 ] || { echo "VP_MODELS_FAIL found=$found (expected 3)"; find "$SRC" -name '*.onnx' -not -path '*/.git/*'; exit 1; }
sha256sum "$DEST"/*.onnx
echo "VP_MODELS_OK"
