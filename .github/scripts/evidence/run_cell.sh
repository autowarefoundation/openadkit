#!/usr/bin/env bash
# shellcheck shell=bash
set -uo pipefail

# Run one evidence cell against a staged kit (run from the kit root):
#   L0: ./openadkit validate
#   L1: ./openadkit run + readiness (services, topics, freshness)
#   L2: planning-simulation golden path or scenario-simulation samples
#
# Writes cell.json, per-step logs and metrics under the output directory, and
# collects container logs plus the scenario output when the cell fails.
#
# Usage: run_cell.sh <deployment> <distro> <output-dir> [node]
# Env:   PLATFORM, BUILD_TAG, SOURCE_SHA, API_SERVICES, API_TOPICS, FRESH_TOPICS

deployment=${1:?usage: run_cell.sh <deployment> <distro> <output-dir> [node]}
distro=${2:?}
out=${3:?}
node=${4:-}

platform=${PLATFORM:-linux/amd64}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "${out}"

project="openadkit-${deployment}"
node_args=()
if [ -n "${node}" ]; then
    project="${project}-${node}"
    node_args=(--node "${node}")
fi
cell_name="${deployment}-${distro}${node:+-${node}}-${platform//\//-}"

api_container=autoware-api
api_services=${API_SERVICES:-/api/localization/initialize /api/routing/set_route_points /api/operation_mode/change_to_autonomous}
api_topics=${API_TOPICS:-/api/routing/state /api/localization/initialization_state /api/operation_mode/state}
fresh_topics=${FRESH_TOPICS:-/clock}

result="PASSED"
l0_ok=false
l1_ok=false
l2_ok="null"
ready_s="null"
arrival_s="null"
scenario_json="null"

sample_memory() {
    local peak=0 ids sum
    while :; do
        ids=$(docker ps -q --filter "label=com.docker.compose.project=${project}" 2>/dev/null)
        if [ -n "${ids}" ]; then
            # shellcheck disable=SC2086
            sum=$(docker stats --no-stream --format '{{.MemUsage}}' ${ids} 2>/dev/null | awk '{
                v=$1; u=$1;
                gsub(/[0-9.]/,"",u); gsub(/[^0-9.]/,"",v);
                if (u=="GiB") v*=1024; else if (u=="KiB") v/=1024; else if (u=="B") v/=1048576;
                s+=v } END { printf "%d", s+0 }')
            if [ -n "${sum}" ] && [ "${sum}" -gt "${peak}" ] 2>/dev/null; then
                peak="${sum}"
                echo "${peak}" >"${out}/.peak_mib"
            fi
        fi
        sleep 2
    done
}

cleanup() {
    kill "${sampler_pid:-}" 2>/dev/null
    wait "${sampler_pid:-}" 2>/dev/null
    ./openadkit stop "${deployment}" "${node_args[@]}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sample_memory &
sampler_pid=$!

# --- L0: manifest and compose validation -------------------------------------
./openadkit validate "${deployment}" --ros-distro "${distro}" "${node_args[@]}" >"${out}/validate.log" 2>&1
l0_rc=$?
if [ "${l0_rc}" -eq 0 ]; then
    l0_ok=true
else
    result="FAILED"
fi

# --- L1: start the stack and check readiness ---------------------------------
ready_rc=1
if [ "${l0_rc}" -eq 0 ]; then
    run_start=$(date +%s)
    ./openadkit run "${deployment}" --ros-distro "${distro}" "${node_args[@]}" >"${out}/run.log" 2>&1
    run_rc=$?

    if [ "${run_rc}" -eq 0 ] && docker inspect "${api_container}" >/dev/null 2>&1; then
        docker cp "${script_dir}/readiness.py" "${api_container}:/tmp/openadkit-readiness.py" >/dev/null 2>&1 || true
        read_args=(--timeout 300 --output /tmp/readiness.json)
        for name in ${api_services}; do read_args+=(--service "${name}"); done
        for name in ${api_topics}; do read_args+=(--topic "${name}"); done
        for name in ${fresh_topics}; do read_args+=(--fresh "${name}"); done
        docker exec "${api_container}" bash -lc \
            "source /opt/ros/${distro}/setup.bash; source /opt/autoware/setup.sh; python3 /tmp/openadkit-readiness.py \"\$@\"" \
            readiness "${read_args[@]}" >"${out}/readiness.log" 2>&1
        ready_rc=$?
        docker cp "${api_container}:/tmp/readiness.json" "${out}/readiness.json" >/dev/null 2>&1 || true
        ready_s=$(( $(date +%s) - run_start ))
        if [ "${ready_rc}" -eq 0 ]; then
            l1_ok=true
        else
            result="FAILED"
        fi
    else
        echo "run failed (rc=${run_rc}) or ${api_container} is missing" >"${out}/readiness.log"
        result="FAILED"
    fi
fi

# --- L2: end-to-end behaviour -------------------------------------------------
if [ "${l1_ok}" = true ]; then
    case "${deployment}" in
        planning-simulation)
            docker cp "${script_dir}/golden.py" "${api_container}:/tmp/openadkit-golden.py" >/dev/null 2>&1 || true
            golden_start=$(date +%s)
            docker exec "${api_container}" bash -lc \
                "source /opt/ros/${distro}/setup.bash; source /opt/autoware/setup.sh; timeout 900 python3 /tmp/openadkit-golden.py" \
                >"${out}/golden.log" 2>&1
            golden_rc=$?
            arrival_s=$(( $(date +%s) - golden_start ))
            if [ "${golden_rc}" -eq 0 ]; then
                l2_ok=true
            else
                l2_ok=false
                result="FAILED"
            fi
            ;;
        scenario-simulation)
            ss_rc=$(timeout 1200 docker wait autoware-scenario-simulator 2>/dev/null || echo timeout)
            docker logs autoware-scenario-simulator >"${out}/scenario.log" 2>&1 || true
            python3 "${script_dir}/scenario_metrics.py" \
                --output-dir "deployments/scenario-simulation/output" \
                --log "${out}/scenario.log" \
                --json "${out}/scenario.json" >"${out}/scenario-metrics.log" 2>&1
            metrics_rc=$?
            [ -f "${out}/scenario.json" ] && scenario_json=$(cat "${out}/scenario.json")
            if [ "${ss_rc}" = "0" ] && [ "${metrics_rc}" -eq 0 ]; then
                l2_ok=true
            else
                l2_ok=false
                result="FAILED"
            fi
            ;;
        *)
            l2_ok="null"
            ;;
    esac
fi

# --- artifacts ---------------------------------------------------------------
peak_mib=$(cat "${out}/.peak_mib" 2>/dev/null || echo 0)
rm -f "${out}/.peak_mib"

if [ "${result}" != "PASSED" ]; then
    mkdir -p "${out}/logs"
    for container_id in $(docker ps -aq --filter "label=com.docker.compose.project=${project}" 2>/dev/null); do
        container_name=$(docker inspect -f '{{.Name}}' "${container_id}" | sed 's#^/##')
        docker logs "${container_id}" >"${out}/logs/${container_name}.log" 2>&1 || true
    done
    cp -a deployments/scenario-simulation/output "${out}/scenario-output" 2>/dev/null || true
fi

jq -n \
    --arg name "${cell_name}" \
    --arg deployment "${deployment}" \
    --arg distro "${distro}" \
    --arg node "${node}" \
    --arg platform "${platform}" \
    --arg result "${result}" \
    --arg build_tag "${BUILD_TAG:-unknown}" \
    --arg source_sha "${SOURCE_SHA:-unknown}" \
    --argjson l0 "${l0_ok}" \
    --argjson l1 "${l1_ok}" \
    --argjson l2 "${l2_ok}" \
    --argjson ready_s "${ready_s}" \
    --argjson arrival_s "${arrival_s}" \
    --argjson peak_mib "${peak_mib}" \
    --argjson scenario "${scenario_json}" \
    '{
        name: $name,
        deployment: $deployment,
        distro: $distro,
        node: $node,
        platform: $platform,
        result: $result,
        build_tag: $build_tag,
        source_sha: $source_sha,
        levels: {
            L0: {ok: $l0},
            L1: {ok: $l1, ready_s: $ready_s},
            L2: {ok: $l2, arrival_s: $arrival_s, scenario: $scenario}
        },
        metrics: {ready_s: $ready_s, arrival_s: $arrival_s, peak_mib: $peak_mib}
    }' >"${out}/cell.json"

echo "cell ${cell_name}: ${result} (L0=${l0_ok} L1=${l1_ok} L2=${l2_ok})"
[ "${result}" = "PASSED" ]