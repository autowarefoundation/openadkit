#!/usr/bin/env bash
# Diff two board manifests (x5h-manifest.sh output) after removing the keys
# whose values legitimately derive from boards/<board>.vars.
#   x5h-parity.sh <manifest1> <vars1> <manifest2> <vars2>
# Terminal marker: BOARD_PARITY_PASS | BOARD_PARITY_FAIL reason=<residual_diff|bad_args>
set -u
[ $# -eq 4 ] || { echo "BOARD_PARITY_FAIL reason=bad_args"; exit 2; }
m1=$1 v1=$2 m2=$3 v2=$4
for f in "$m1" "$v1" "$m2" "$v2"; do [ -r "$f" ] || { echo "BOARD_PARITY_FAIL reason=bad_args file=$f"; exit 2; }; done
# Keys allowed to differ: derived from the vars file and nothing else.
#   boot.x5h-env.txt      rendered env differs in ip=/hostname
#   boot.x5h-role.txt     the sticky role is operational state, not config
#   file./etc/x5h/board.conf, hostname, file./etc/hostname
#   fs.yocto-*            the Yocto partitions are populated only where HAS_YOCTO=1
#   file./etc/ssh/ssh_host_*  host keys are per board by nature
allow='^(boot\.x5h-env\.txt|boot\.x5h-role\.txt|file\./etc/x5h/board\.conf|file\./etc/hostname|hostname|fs\.yocto-.*|file\./etc/ssh/ssh_host_.*)	'
strip() { grep -Ev "$allow" "$1" | sort; }
residual=$(diff <(strip "$m1") <(strip "$m2"))
if [ -z "$residual" ]; then
    echo "BOARD_PARITY_PASS"
    exit 0
fi
echo "$residual"
echo "BOARD_PARITY_FAIL reason=residual_diff"
exit 1
