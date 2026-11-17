#!/usr/bin/env bash
# setup.sh's host probes must not fail under pipefail when a pipeline's first
# command writes more than the reader consumes (SIGPIPE).
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

# A large ldconfig output with the match first: grep -q exits at once.
cat >"${work}/ldconfig" <<'PROBE'
#!/usr/bin/env bash
echo "libGLX_nvidia.so.0 (libc6,x86-64) => /usr/lib/libGLX_nvidia.so.0"
for i in $(seq 1 20000); do echo "libother${i}.so.0 (libc6,x86-64) => /usr/lib/libother${i}.so.0"; done
PROBE
chmod +x "${work}/ldconfig"
# A silent ldconfig, so the negative stays meaningful.
cat >"${work}/ldconfig-silent" <<'PROBE'
#!/usr/bin/env bash
echo "libc.so.6 (libc6,x86-64) => /lib/x86_64-linux-gnu/libc.so.6"
PROBE
chmod +x "${work}/ldconfig-silent"

# Source the helper without its main body.
# shellcheck disable=SC1090,SC1091
source "${SETUP:-${root}/cli/setup.sh}"

PATH="${work}:${PATH}"
nvidia_gl_libraries_present || { echo "present library reported missing under pipefail" >&2; exit 1; }

rename() { mv "${work}/ldconfig" "${work}/ldconfig.present"; mv "${work}/ldconfig-silent" "${work}/ldconfig"; }
rename
if nvidia_gl_libraries_present; then echo "absent library reported present" >&2; exit 1; fi

# setup checks the host by default: --no-check skips it, and the old --check,
# which other commands use for "report only", is refused before any change.
setup_script="${SETUP:-${root}/cli/setup.sh}"
help=$(bash "${setup_script}" setup --help)
grep -q -- '--no-check' <<<"${help}" || { echo "setup --help does not name --no-check" >&2; exit 1; }
status=0
bash "${setup_script}" setup --check >/dev/null 2>&1 || status=$?
[[ ${status} -eq 2 ]] || { echo "setup --check exited ${status}, expected a usage error" >&2; exit 1; }
echo "setup helper probes pass"
