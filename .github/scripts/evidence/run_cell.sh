#!/usr/bin/env bash
# shellcheck shell=bash
set -uo pipefail

# Run one evidence cell against a staged kit (run from the kit root):
#   L0: ./openadkit validate
#   L1: ./openadkit run + readiness (services, topics, freshness)
#   L2: planning-simulation golden path, scenario-simulation samples, or the
#       split-node variant (autoware + scenario nodes on one host) with a
#       domain-isolation check.
#
# Writes cell.json, per-step logs and metrics under the output directory, and
# collects container logs plus the scenario output when the cell fails.
#
# Usage: run_cell.sh <deployment> <distro> <output-dir> [node]
#   node: "" (single host), a node name, or "split"
# Env:   PLATFORM, BUILD_TAG, SOURCE_SHA, API_SERVICES, API_TOPICS, FRESH_TOPICS,
#        SPLIT_ZENOH_AUTOWARE, SPLIT_ZENOH_SCENARIO, SPLIT_ZENOH_PEER

deployment=${1:?usage: run_cell.sh <deployment> <distro> <output-dir> [node]}
distro=${2:?}
out=${3:?}
node=${4:-}

platform=${PLATFORM:-linux/amd64}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "${out}"
# Keep run results with this cell's evidence instead of the runner's home.
export OPENADKIT_STATE_DIR="${out}/state"
scenario_output="${OPENADKIT_STATE_DIR}/${deployment}/output"

split=false
node_args=()
projects=("openadkit-${deployment}")
if [ "${node}" = "split" ]; then
    split=true
    projects=("openadkit-${deployment}-autoware" "openadkit-${deployment}-scenario")
elif [ -n "${node}" ]; then
    projects=("openadkit-${deployment}-${node}")
    node_args=(--node "${node}")
fi
cell_name="${deployment}-${distro}${node:+-${node}}-${platform//\//-}"

api_container=autoware-api
api_services=${API_SERVICES:-/api/localization/initialize /api/routing/set_route_points /api/operation_mode/change_to_autonomous}
api_topics=${API_TOPICS:-/api/routing/state /api/localization/initialization_state /api/operation_mode/state}
# Topics that flow without a route or an initial pose: the system's operation
# mode availability in every deployment, plus the simulation clock where the
# deployment runs on sim time. Planning Simulation runs on wall time and has
# no /clock.
default_fresh=/system/operation_mode/availability
if [ "${deployment}" = scenario-simulation ]; then
    default_fresh="${default_fresh} /clock"
fi
fresh_topics=${FRESH_TOPICS:-${default_fresh}}
zenoh_autoware=${SPLIT_ZENOH_AUTOWARE:-tcp/127.0.0.1:7447}
zenoh_scenario=${SPLIT_ZENOH_SCENARIO:-tcp/127.0.0.1:7448}
zenoh_peer=${SPLIT_ZENOH_PEER:-tcp/127.0.0.1:7447}

result="PASSED"
l0_ok=false
l1_ok=false
l2_ok="null"
ready_s="null"
arrival_s="null"
isolation="null"
scenario_json="null"

sample_memory() {
    local peak=0 ids sum
    while :; do
        ids=""
        for name in "${projects[@]}"; do
            ids+=" $(docker ps -q --filter "label=com.docker.compose.project=${name}" 2>/dev/null)"
        done
        if [ -n "${ids// /}" ]; then
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
    if [ "${split}" = true ]; then
        ./openadkit stop "${deployment}" --node scenario >/dev/null 2>&1 || true
        ./openadkit stop "${deployment}" --node autoware >/dev/null 2>&1 || true
    else
        ./openadkit stop "${deployment}" "${node_args[@]}" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

sample_memory &
sampler_pid=$!

# --- L0: manifest and compose validation -------------------------------------
validate_node_args=()
[ -n "${node}" ] && [ "${node}" != "split" ] && validate_node_args=(--node "${node}")
if [ "${split}" = true ]; then
    # Both node views must validate.
    ./openadkit validate "${deployment}" --node autoware --ros-distro "${distro}" >"${out}/validate-autoware.log" 2>&1
    rc_a=$?
    ./openadkit validate "${deployment}" --node scenario --ros-distro "${distro}" >"${out}/validate-scenario.log" 2>&1
    rc_b=$?
    l0_rc=$(( rc_a != 0 || rc_b != 0 ))
else
    ./openadkit validate "${deployment}" --ros-distro "${distro}" "${validate_node_args[@]}" >"${out}/validate.log" 2>&1
    l0_rc=$?
fi
if [ "${l0_rc}" -eq 0 ]; then
    l0_ok=true
else
    result="FAILED"
fi

# --- L1: start the stack and check readiness ---------------------------------
if [ "${l0_rc}" -eq 0 ]; then
    run_start=$(date +%s)
    if [ "${split}" = true ]; then
        ZENOH_LISTEN="${zenoh_autoware}" \
            ./openadkit run "${deployment}" --node autoware --ros-distro "${distro}" >"${out}/run-autoware.log" 2>&1
        rc_a=$?
        ZENOH_LISTEN="${zenoh_scenario}" ZENOH_PEER="${zenoh_peer}" \
            ./openadkit run "${deployment}" --node scenario --ros-distro "${distro}" >"${out}/run-scenario.log" 2>&1
        rc_b=$?
        run_rc=$(( rc_a != 0 || rc_b != 0 ))
    else
        ./openadkit run "${deployment}" --ros-distro "${distro}" "${node_args[@]}" >"${out}/run.log" 2>&1
        run_rc=$?
    fi

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
                --output-dir "${scenario_output}" \
                --log "${out}/scenario.log" \
                --json "${out}/scenario.json" >"${out}/scenario-metrics.log" 2>&1
            metrics_rc=$?

            if [ "${split}" = true ]; then
                # Isolation: without the scenario node's bridge, domain 2 must
                # not see the autoware node's /api topics.
                bridge=$(
                    docker ps -q \
                        --filter "label=com.docker.compose.project=openadkit-${deployment}-scenario" |
                        while read -r id; do
                            docker inspect -f '{{.Name}}' "${id}"
                        done | grep zenoh-bridge || true
                )
                if [ -n "${bridge}" ]; then
                    docker stop "${bridge}" >/dev/null 2>&1 || true
                    sleep 5
                    image=$(docker inspect -f '{{.Config.Image}}' autoware-scenario-simulator 2>/dev/null || true)
                    isolation=$(
                        docker run --rm --network host \
                            -e ROS_DOMAIN_ID=2 \
                            -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
                            -e CYCLONEDDS_URI=file:///etc/cyclonedds/cyclonedds.xml \
                            -e "ROS_DISTRO=${distro}" \
                            -v "${PWD}/deployments/shared/cyclonedds.xml:/etc/cyclonedds/cyclonedds.xml:ro" \
                            --entrypoint bash "${image}" -c \
                            "source /opt/ros/${distro}/setup.bash; timeout 20 ros2 topic list 2>/dev/null | grep -c '^/api/'" 2>/dev/null || echo failed
                    )
                else
                    isolation=failed
                fi
                [ -f "${out}/scenario.json" ] &&
                    jq -c --argjson iso "${isolation}" '. + {isolation_api_topics: $iso}' "${out}/scenario.json" >"${out}/scenario.json.tmp" &&
                    mv "${out}/scenario.json.tmp" "${out}/scenario.json"
            fi

            [ -f "${out}/scenario.json" ] && scenario_json=$(cat "${out}/scenario.json")
            if [ "${ss_rc}" = "0" ] && [ "${metrics_rc}" -eq 0 ] && [ "${isolation}" != "failed" ] && { [ "${isolation}" = "null" ] || [ "${isolation}" = "0" ]; }; then
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
    for name in "${projects[@]}"; do
        for container_id in $(docker ps -aq --filter "label=com.docker.compose.project=${name}" 2>/dev/null); do
            container_name=$(docker inspect -f '{{.Name}}' "${container_id}" | sed 's#^/##')
            docker logs "${container_id}" >"${out}/logs/${container_name}.log" 2>&1 || true
        done
    done
    cp -a "${scenario_output}" "${out}/scenario-output" 2>/dev/null || true
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

echo "cell ${cell_name}: ${result} (L0=${l0_ok} L1=${l1_ok} L2=${l2_ok} isolation=${isolation})"
[ "${result}" = "PASSED" ]