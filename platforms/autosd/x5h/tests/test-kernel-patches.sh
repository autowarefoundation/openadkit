#!/usr/bin/env bash
# Every patch under kernel/patches must apply cleanly to the pinned source.
# KERNEL_SRC must name a pristine extracted linux-bsp tree at the SHA
# build-bsp-kernel.sh pins. No tree, no test: this fails, never skips.
set -u
name=test-kernel-patches
here=$(cd "$(dirname "$0")" && pwd)
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -n "${KERNEL_SRC:-}" ] || fail KERNEL_SRC_unset
[ -f "$KERNEL_SRC/drivers/rpmsg/virtio_rpmsg_bus.c" ] || fail not_a_kernel_tree
grep -q '^SHA=ff9ce02daad0f5a4e64984d725f488faf3cf3e71$' "$here/../kernel/build-bsp-kernel.sh" || fail pinned_sha_moved_update_this_test
case "$KERNEL_SRC" in *ff9ce02daad0f5a4e64984d725f488faf3cf3e71*) ;; *) fail tree_is_not_the_pinned_sha ;; esac
n=0
for p in "$here"/../kernel/patches/*.patch; do
    [ -e "$p" ] || fail no_patches
    patch -p1 -N --dry-run -d "$KERNEL_SRC" < "$p" >/dev/null 2>&1 || fail "does_not_apply_$(basename "$p")"
    n=$((n + 1))
done
grep -q '^+#define MAX_RPMSG_BUF_SIZE[[:space:]]*(2048)$' "$here"/../kernel/patches/0001-rpmsg-virtio-raise-buffer-size-to-2048.patch || fail buffer_size_not_2048
grep -q 'patches/\*\.patch' "$here/../kernel/build-bsp-kernel.sh" || fail build_script_does_not_apply_patches
echo "TEST_PASS $name patches=$n"
