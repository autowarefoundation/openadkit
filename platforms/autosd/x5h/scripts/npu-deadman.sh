#!/bin/sh
# Reboot if no heartbeat within the deadline. A reboot returns the board to
# Yocto (bootcmd probes LUN 3 first), so this is a return-to-safety, not a
# reset loop. Defer by: touch /run/npu-heartbeat
set -u
HB=/run/npu-heartbeat
DEADLINE=1800
[ -f "$HB" ] || { touch "$HB"; exit 0; }
AGE=$(( $(date +%s) - $(stat -c %Y "$HB") ))
[ $AGE -lt $DEADLINE ] && exit 0
logger -t npu-deadman "no heartbeat for ${AGE}s (deadline ${DEADLINE}s), rebooting to Yocto"
sync
systemctl reboot --force
