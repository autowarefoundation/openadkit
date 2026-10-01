#!/usr/bin/env bash
# Assemble the build context for visionpilot-x5h.containerfile.
#   prepare-vp-context.sh <ort-overlay-dir> <out-dir>
# <ort-overlay-dir> holds include/ (upstream onnxruntime 1.24.1 headers; 1.24.0
# ships no aarch64 tarball) and lib/libonnxruntime.so.1.24.0 (the vendor build
# carrying RenesasExecutionProvider). The vendor library is NDA material and
# lives under x5h-work/; this script copies it into a throwaway context and
# nothing under the repo. VisionPilot reaches the provider through
# AppendExecutionProvider("RenesasExecutionProvider", ...), so no vendor
# header is needed.
# Headers stay FLAT (include/onnxruntime_cxx_api.h, not
# include/onnxruntime/onnxruntime_cxx_api.h): every VisionPilot consumer
# includes them with no prefix (engine/onnx_engine.hpp and friends), and
# only ${ONNXRUNTIME_ROOT}/include is ever added to the include path
# (modules/engine/CMakeLists.txt, modules/logging/CMakeLists.txt). That is
# also how the upstream onnxruntime-linux-aarch64 tarball ships include/.
set -uo pipefail
OV="${1:-}"; OUT="${2:-}"
fail() { echo "VP_CONTEXT_FAIL reason=$1"; exit 1; }
[ -n "$OV" ] && [ -n "$OUT" ] || fail bad_args
[ -f "$OV/include/onnxruntime_cxx_api.h" ] || fail no_headers
LIB="$OV/lib/libonnxruntime.so.1.24.0"; [ -f "$LIB" ] || fail no_vendor_lib
strings_out=$(strings -n 20 "$LIB" 2>/dev/null || cat "$LIB")
grep -q 'RenesasExecutionProvider' <<<"$strings_out" || fail ep_string_missing
rm -rf "$OUT" && mkdir -p "$OUT/ort/lib" || fail mkdir
cp -a "$OV/include" "$OUT/ort/include" || fail copy_headers
cp "$LIB" "$OUT/ort/lib/" || fail copy_lib
ln -s libonnxruntime.so.1.24.0 "$OUT/ort/lib/libonnxruntime.so.1"
ln -s libonnxruntime.so.1 "$OUT/ort/lib/libonnxruntime.so"
echo "VP_CONTEXT_PASS dir=$OUT"
