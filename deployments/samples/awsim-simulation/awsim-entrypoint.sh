#!/usr/bin/env bash
set -euo pipefail

AWSIM_HEADLESS=${AWSIM_HEADLESS:-true}
AWSIM_XVFB_SERVER_NUM=${AWSIM_XVFB_SERVER_NUM:-98}
AWSIM_XVFB_SCREEN=${AWSIM_XVFB_SCREEN:-1280x720x24}
AWSIM_RESX=${AWSIM_RESX:-1280}
AWSIM_RESY=${AWSIM_RESY:-720}
AWSIM_LOG_FILE=${AWSIM_LOG_FILE:--}
AWSIM_CONFIG_PATH=${AWSIM_CONFIG_PATH:-}

if [[ -n "${AWSIM_EXECUTABLE:-}" ]]; then
  executable=$AWSIM_EXECUTABLE
else
  executable=$(find /opt/awsim -name 'AWSIM*.x86_64' -print -quit)
fi

if [[ -z "$executable" || ! -x "$executable" ]]; then
  printf 'AWSIM executable was not found or is not executable: %s\n' "$executable" >&2
  exit 1
fi

cd "$(dirname "$executable")"
executable=./$(basename "$executable")

args=(
  "$executable"
  -force-vulkan
  -screen-width "$AWSIM_RESX"
  -screen-height "$AWSIM_RESY"
  -logFile "$AWSIM_LOG_FILE"
)

if [[ -n "$AWSIM_CONFIG_PATH" ]]; then
  args+=(--json_path "$AWSIM_CONFIG_PATH")
fi

if [[ $# -gt 0 ]]; then
  args+=("$@")
fi

if [[ "$AWSIM_HEADLESS" == true ]]; then
  exec xvfb-run -n "$AWSIM_XVFB_SERVER_NUM" -s "-screen 0 ${AWSIM_XVFB_SCREEN}" "${args[@]}"
fi

exec "${args[@]}"
