#!/usr/bin/env bash
# Host-side checks on aib/x5h-rootfs.aib.yml. No board, no root, no network.
#
# Two classes of defect, both of which have actually happened here:
#   1. a source_path that does not resolve -- invisible until a ~23 minute CI
#      image build fails on it;
#   2. an operator-run checker that the documents route people to but the
#      image does not install, so a board freshly written by
#      `stage-board.sh write-root` does not have it. That is the staleness
#      trap the manifest's own x5h-stack-smoke.sh comment describes: the
#      alternative is a hand-copied checker that goes stale and then grades a
#      board against a contract that no longer exists.
set -u
name=test-aib-manifest
here=$(cd "$(dirname "$0")" && pwd)
aibdir="$here/../aib"
aib="$aibdir/x5h-rootfs.aib.yml"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -f "$aib" ] || fail manifest_missing

# --- every source_path resolves, relative to the manifest's directory ------
n=0
while IFS= read -r sp; do
    n=$((n + 1))
    [ -e "$aibdir/$sp" ] || fail "unresolved_source_path=$sp"
done < <(sed -n 's/^[[:space:]]*-[[:space:]]*source_path:[[:space:]]*//p' "$aib")
[ "$n" -gt 0 ] || fail no_source_paths

# --- the four operator-run smokes ship in the image, under /usr/sbin ------
# aib refuses /usr/local and /opt outright (both are symlinks into /var on
# this ostree-structured rootfs and the build aborts), so /usr/sbin is the
# only option -- see the make_dirs commentary in the manifest.
for smoke in selfboot-smoke.sh rpmsg-eth-smoke.sh npu-contract-smoke.sh x5h-stack-smoke.sh; do
    [ -f "$here/../scripts/$smoke" ] || fail "script_missing=$smoke"
    grep -A1 -F "source_path: ../scripts/$smoke" "$aib" \
        | grep -qF "path: /usr/sbin/$smoke" || fail "not_installed_to_usr_sbin=$smoke"
done

# --- no destination aib rejects ------------------------------------------
sed -n 's/^[[:space:]]*path:[[:space:]]*//p' "$aib" | grep -Eq '^(/usr/local|/opt)/' \
    && fail rejected_destination_prefix

# --- the documents must invoke them where the image puts them -------------
# A doc that still says /usr/local/bin sends the operator to a path that does
# not exist on a freshly written board, which reads as a broken image rather
# than as a stale sentence.
for doc in selfboot.md companion-host.md rpmsg-dualboot.md; do
    [ -f "$here/../$doc" ] || fail "doc_missing=$doc"
    grep -q '/usr/local/bin/selfboot-smoke\.sh' "$here/../$doc" && fail "stale_smoke_path_in=$doc"
done
grep -q '/usr/sbin/selfboot-smoke\.sh' "$here/../selfboot.md" || fail selfboot_md_no_usr_sbin_path
grep -q '/usr/sbin/rpmsg-eth-smoke\.sh' "$here/../selfboot.md" || fail selfboot_md_no_rpmsg_smoke_path

echo "TEST_PASS $name"
