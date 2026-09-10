#!/usr/bin/env bash
# Diff two board manifests (x5h-manifest.sh output) after removing the keys
# whose values legitimately derive from boards/<board>.vars.
#   x5h-parity.sh <manifest1> <vars1> <manifest2> <vars2>
# Terminal marker:
#   BOARD_PARITY_PASS
#   BOARD_PARITY_FAIL reason=<residual_diff|bad_args|same_manifest|bad_vars|incomplete_manifest>
set -u
[ $# -eq 4 ] || { echo "BOARD_PARITY_FAIL reason=bad_args"; exit 2; }
m1=$1 v1=$2 m2=$3 v2=$4
for f in "$m1" "$v1" "$m2" "$v2"; do [ -r "$f" ] || { echo "BOARD_PARITY_FAIL reason=bad_args file=$f"; exit 2; }; done

# Being handed the same manifest twice is a plausible operator slip and it
# always compares clean, so refuse it rather than certify it.
r1=$(readlink -f "$m1") || r1=$m1
r2=$(readlink -f "$m2") || r2=$m2
[ "$r1" != "$r2" ] || { echo "BOARD_PARITY_FAIL reason=same_manifest file=$m1"; exit 2; }

# Completeness floor. x5h-manifest.sh silences nothing any more, but a manifest
# produced by an older copy of it -- or truncated in transit -- can still lose a
# whole category symmetrically on both boards, and two equally-gutted manifests
# compare equal. Require the categories whose absence hides the most: the
# kernel, the command line, the boot partition (which carries the kernel image
# and the U-Boot env) and the unit enablement state.
require_complete() {
    local f=$1 label pat
    if grep -q 'X5H_MANIFEST_FAIL' "$f"; then
        echo "BOARD_PARITY_FAIL reason=incomplete_manifest manifest=$f missing=manifest_marked_failed"
        exit 2
    fi
    if [ ! -s "$f" ]; then
        echo "BOARD_PARITY_FAIL reason=incomplete_manifest manifest=$f missing=all_keys"
        exit 2
    fi
    for label in 'kernel' 'cmdline' 'env.md5' 'boot.*' 'unit.*'; do
        case $label in
            *'.*') pat="^${label%.\*}\\." ;;
            *)     pat="^$label"$'\t' ;;
        esac
        grep -Eq "$pat" "$f" || {
            echo "BOARD_PARITY_FAIL reason=incomplete_manifest manifest=$f missing=$label"
            exit 2
        }
    done
}
require_complete "$m1"
require_complete "$m2"

# HAS_YOCTO decides one exemption, so it must actually be read. Anything other
# than 0 or 1 is a broken vars file, not a default.
read_has_yocto() {
    local val
    val=$(sed -n 's/^[[:space:]]*HAS_YOCTO[[:space:]]*=[[:space:]]*\([^[:space:]#]*\).*/\1/p' "$1" | tail -1 | tr -d "\"'")
    case $val in
        0|1) printf '%s' "$val" ;;
        *)   return 1 ;;
    esac
}
y1=$(read_has_yocto "$v1") || { echo "BOARD_PARITY_FAIL reason=bad_vars file=$v1 key=HAS_YOCTO"; exit 2; }
y2=$(read_has_yocto "$v2") || { echo "BOARD_PARITY_FAIL reason=bad_vars file=$v2 key=HAS_YOCTO"; exit 2; }

# Keys allowed to differ: derived from the vars file and nothing else.
#   boot.x5h-env.txt      rendered env differs in ip=/hostname; the rest of the
#                         env is covered by env.md5, which is NOT exempt
#   boot.x5h-role.txt     the sticky role is operational state, not config
#   file./etc/x5h/board.conf, hostname, file./etc/hostname
#   file./etc/ssh/ssh_host_*  host keys are per board by nature
#   file./etc/ssh/authorized_keys.d/*  root-access grants are per board BY
#                         DESIGN: board 1 carries admin + dev + ext, board 2
#                         admin only (companion-host.md, "The two boards"),
#                         and stage-board.sh's backup-keys/prepare-root pair
#                         deliberately carries each board's own live file
#                         forward across a re-image. Comparing them for
#                         equality therefore makes BOARD_PARITY_PASS
#                         unreachable on the real bench. The keys are still
#                         EMITTED into the manifest, so a human reading the
#                         two manifests side by side still sees exactly who
#                         is granted where; only the verdict is exempt.
#                         Never close this the other way by equalising the
#                         two boards' keys: that grants board 2 to external
#                         developers, which the access model forbids.
# The character before each closing quote is a literal TAB (the manifest's
# key/value separator); a run of spaces there breaks the match invisibly.
allow='^(boot\.x5h-env\.txt|boot\.x5h-role\.txt|file\./etc/x5h/board\.conf|file\./etc/hostname|hostname|file\./etc/ssh/ssh_host_.*|file\./etc/ssh/authorized_keys\.d/.*)	'
# fs.yocto-* is exempt ONLY when the two boards disagree about HAS_YOCTO, i.e.
# when one board is expected to carry a populated Yocto filesystem and the other
# is not. When both boards set HAS_YOCTO=1 (or both 0) a divergence in those
# filesystems is a genuine defect and must be compared.
allow_yocto='^fs\.yocto-.*	'

if [ "$y1" != "$y2" ]; then
    strip() { grep -Ev "$allow" "$1" | grep -Ev "$allow_yocto" | sort; }
else
    strip() { grep -Ev "$allow" "$1" | sort; }
fi

residual=$(diff <(strip "$m1") <(strip "$m2"))
if [ -z "$residual" ]; then
    echo "BOARD_PARITY_PASS"
    exit 0
fi
echo "$residual"
echo "BOARD_PARITY_FAIL reason=residual_diff"
exit 1
