#!/usr/bin/env bash
# Invariants of the S-CORE launch manager configurations that the schema does
# not check: the LM truncates argv at 20 without an error, VisionPilot is the
# only supervised component, the fallback holds the fault component and never
# VisionPilot, and no Safety Island unit is an LM component.
set -u
name=test-score-lm-config
here=$(cd "$(dirname "$0")" && pwd)
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
for c in demo sil; do
    f="$here/../score/config/$c/launch_manager_config.json"
    [ -f "$f" ] || fail "missing_$c"
    out=$(python3 - "$f" <<'EOF'
import json, sys
cfg = json.load(open(sys.argv[1]))
comps = cfg["components"]
for n, c in comps.items():
    args = c["component_properties"].get("process_arguments", [])
    if len(args) > 20:
        print(f"too_many_args_{n}"); sys.exit()
sup = [n for n, c in comps.items()
       if c["component_properties"].get("application_profile", {}).get("application_type") == "Reporting_And_Supervised"]
if sup != ["visionpilot"]:
    print("supervised=" + ",".join(sup)); sys.exit()
vp = comps["visionpilot"]
if "file_state" not in vp["component_properties"].get("ready_condition", {}):
    print("vp_not_file_ready"); sys.exit()
env = vp["deployment_config"]["environmental_variables"]
for k in ("PATH", "IDENTIFIER", "SCORE_VP_FRAME_MAX_MS", "SCORE_VP_READY_FILE"):
    if k not in env:
        print(f"vp_env_missing_{k}"); sys.exit()
fb = cfg["fallback_run_target"]["depends_on"]
if fb != ["si_fault"]:
    print("fallback=" + ",".join(fb)); sys.exit()
if cfg["initial_run_target"] != "Startup":
    print("initial_not_startup"); sys.exit()
for n in comps:
    if any(s in n for s in ("si-link", "si_link", "bridge", "restamp", "hb")):
        print(f"si_path_component_{n}"); sys.exit()
print("ok")
EOF
)
    [ "$out" = ok ] || fail "${c}_$out"
done
echo "TEST_PASS $name"
