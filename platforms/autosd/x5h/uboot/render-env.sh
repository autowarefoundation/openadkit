#!/usr/bin/env bash
# Render uboot/x5h-env.tmpl for one board.
#   render-env.sh boards/x5h1.vars > x5h-env.txt
# The vars file is the ONLY per-board input; everything else is the template.
set -euo pipefail
vars=${1:?usage: render-env.sh <boards/xxx.vars>}
here=$(cd "$(dirname "$0")" && pwd)
tmpl="$here/x5h-env.tmpl"
[ -r "$vars" ] || { echo "FATAL: vars file not readable: $vars" >&2; exit 1; }
[ -r "$tmpl" ] || { echo "FATAL: template missing: $tmpl" >&2; exit 1; }
BOARD_IP= BOARD_HOSTNAME= HAS_YOCTO=
# shellcheck disable=SC1090
. "$vars"
for k in BOARD_IP BOARD_HOSTNAME HAS_YOCTO; do
    [ -n "${!k}" ] || { echo "FATAL: $vars does not set $k" >&2; exit 1; }
done
case "$HAS_YOCTO" in 0|1) ;; *) echo "FATAL: HAS_YOCTO must be 0 or 1, got '$HAS_YOCTO'" >&2; exit 1 ;; esac
YOCTO_HOSTNAME="yocto-${BOARD_HOSTNAME#autosd-}"
sed -e "s|@BOARD_IP@|$BOARD_IP|g" \
    -e "s|@BOARD_HOSTNAME@|$BOARD_HOSTNAME|g" \
    -e "s|@YOCTO_HOSTNAME@|$YOCTO_HOSTNAME|g" "$tmpl"
