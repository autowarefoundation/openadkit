#!/bin/sh
# Publish the active role: /run/x5h/role for scripts, /etc/motd.d for humans.
set -u
CMDLINE=${X5H_CMDLINE:-/proc/cmdline}
RUN_DIR=${X5H_RUN_DIR:-/run/x5h}
MOTD_DIR=${X5H_MOTD_DIR:-/etc/motd.d}
role=$(tr ' ' '\n' < "$CMDLINE" | sed -n 's/^x5h\.role=//p' | head -1)
role=${role:-unknown}
mkdir -p "$RUN_DIR" "$MOTD_DIR"
printf '%s\n' "$role" > "$RUN_DIR/role"
printf 'X5H boot role: %s   (x5h-role set <cr52|npu|yocto> --reboot to switch)\n' "$role" > "$MOTD_DIR/x5h-role"
