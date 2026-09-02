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

# --- every script the image installs is executable in the image -----------
# add_files has no mode field: it copies content and leaves the destination
# 0644 whatever the source is in git. Three units ExecStart a script under
# /usr/sbin, so a missing chmod_files line is a 203/EXEC on the first boot of
# a freshly written board -- found exactly that way on board 2 on 2026-09-02,
# after the image had already been written to the board. The manifest is the
# only place that can fix it, and this check is what makes the two lists stay
# in step: it derives the requirement from the add_files block itself, so a
# script added there without a chmod_files line fails here, on the host, in a
# second, rather than on the board 40 minutes into a staging session.
section() {  # $1 = a key under content: -> the lines of its block
    awk -v k="  $1:" '
        index($0, k) == 1 { f = 1; next }
        f && (/^[a-zA-Z_]+:/ || /^  [a-zA-Z_]+:/) { f = 0 }
        f { print }
    ' "$aib"
}
strip() { sed -n "s/^[[:space:]]*-\{0,1\}[[:space:]]*$1:[[:space:]]*//p"; }

add_pairs=$(section add_files | awk '
    /^[[:space:]]*-[[:space:]]*source_path:/ { sub(/^[^:]*:[[:space:]]*/, ""); src = $0; next }
    /^[[:space:]]*path:/ && src != "" { sub(/^[^:]*:[[:space:]]*/, ""); print src "\t" $0; src = "" }
')
[ -n "$add_pairs" ] || fail add_files_unparseable

chmod_block=$(section chmod_files)
[ -n "$chmod_block" ] || fail no_chmod_files_block
# Pair path with the mode that follows it, so a stray mode cannot satisfy a
# path that has none of its own.
chmod_pairs=$(printf '%s\n' "$chmod_block" | awk '
    /^[[:space:]]*-[[:space:]]*path:/ { sub(/^[^:]*:[[:space:]]*/, ""); p = $0; next }
    /^[[:space:]]*mode:/ && p != "" { sub(/^[^:]*:[[:space:]]*/, ""); gsub(/"/, ""); print p "\t" $0; p = "" }
')
[ -n "$chmod_pairs" ] || fail chmod_files_unparseable

while IFS=$'\t' read -r src dest; do
    case "$src" in ../scripts/*) ;; *) continue ;; esac
    case "$dest" in /usr/sbin/*) ;; *) continue ;; esac
    [ -x "$aibdir/$src" ] || continue          # data files (ort-rootfs.container*)
    mode=$(printf '%s\n' "$chmod_pairs" | awk -F'\t' -v d="$dest" '$1 == d { print $2 }')
    [ -n "$mode" ] || fail "executable_not_chmodded=$dest"
    [ "$mode" = 0755 ] || fail "wrong_mode=$dest mode=$mode"
done <<< "$add_pairs"

# And nothing is chmodded that the manifest does not install: a path that
# survives a renamed or deleted add_files entry is a silent no-op at best.
while IFS=$'\t' read -r cpath _; do
    printf '%s\n' "$add_pairs" | awk -F'\t' -v d="$cpath" '$2 == d { found = 1 } END { exit !found }' \
        || fail "chmod_path_not_installed=$cpath"
done <<< "$chmod_pairs"


echo "TEST_PASS $name"
