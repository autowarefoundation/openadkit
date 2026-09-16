#!/usr/bin/env bash
# prepare-vp-context.sh must refuse an overlay without headers or without a
# library that carries the Renesas provider, and assemble a good one.
set -u
name=test-vp-context
here=$(cd "$(dirname "$0")" && pwd); s="$here/../components/demo/prepare-vp-context.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/ov/lib"; out=$(bash "$s" "$tmp/ov" "$tmp/ctx" 2>&1) && fail no_headers_accepted
grep -q 'VP_CONTEXT_FAIL reason=no_headers' <<<"$out" || fail headers_reason
mkdir -p "$tmp/ov/include"; : > "$tmp/ov/include/onnxruntime_cxx_api.h"
printf 'not an ep' > "$tmp/ov/lib/libonnxruntime.so.1.24.0"
out=$(bash "$s" "$tmp/ov" "$tmp/ctx" 2>&1) && fail plain_lib_accepted
grep -q 'VP_CONTEXT_FAIL reason=ep_string_missing' <<<"$out" || fail ep_reason
printf 'xx RenesasExecutionProvider yy' > "$tmp/ov/lib/libonnxruntime.so.1.24.0"
out=$(bash "$s" "$tmp/ov" "$tmp/ctx" 2>&1) || fail "good_rejected $out"
grep -q "^VP_CONTEXT_PASS dir=$tmp/ctx$" <<<"$out" || fail pass_marker
# -L confirms each path is a symlink; -f follows it and confirms it resolves
# to a real regular file, not a dangling link or an absolute host path.
[ -L "$tmp/ctx/ort/lib/libonnxruntime.so" ] && [ -f "$tmp/ctx/ort/lib/libonnxruntime.so" ] || fail symlinks
[ -L "$tmp/ctx/ort/lib/libonnxruntime.so.1" ] && [ -f "$tmp/ctx/ort/lib/libonnxruntime.so.1" ] || fail symlinks
[ -f "$tmp/ctx/ort/include/onnxruntime_cxx_api.h" ] || fail headers_copied
echo "TEST_PASS $name"
