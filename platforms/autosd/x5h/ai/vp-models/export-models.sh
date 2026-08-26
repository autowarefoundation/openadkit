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
if [ ! -d "$SRC/.git" ]; then
  mkdir -p "$SRC" && cd "$SRC" && git init -q && git remote add origin "$VP_REPO"
  git fetch -q --depth 1 origin "$VP_COMMIT" && git checkout -q FETCH_HEAD
fi
mkdir -p "$DEST"
found=0
while IFS= read -r f; do
  case "$(basename "$f")" in
    autodrive_fp32.onnx|autosteer_fp32.onnx|autospeed_fp32.onnx) cp "$f" "$DEST/"; found=$((found+1));;
  esac
done < <(find "$SRC" -name '*.onnx' -not -path '*/.git/*')
[ "$found" -eq 3 ] || { echo "VP_MODELS_FAIL found=$found (expected 3)"; find "$SRC" -name '*.onnx' -not -path '*/.git/*'; exit 1; }
sha256sum "$DEST"/*.onnx
echo "VP_MODELS_OK"
