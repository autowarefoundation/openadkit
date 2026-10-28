#!/usr/bin/env bash
# shellcheck shell=bash
set -uo pipefail

# Run one evidence cell against a staged kit (run from the kit root):
#   L0: ./openadkit validate
#   L1: ./openadkit run + readiness (services, topics, freshness) and the
#       cell's extra L1 check
#   L2: the cell's end-to-end check: the planning-simulation golden path, or
#       the scenario-simulation samples, plus a domain-isolation check when
#       the cell runs several nodes on one host.
#
# The cell is one row of the evidence matrix (validation_matrix.py), which
# derives what to run and check from the manifests; this runner only executes
# it. Writes cell.json, per-step logs and metrics under the output directory,
# and collects container logs plus the scenario output when the cell fails.
#
# Usage: run_cell.sh <cell-json> <output-dir>
# Env:   BUILD_TAG, SOURCE_SHA, API_SERVICES, API_TOPICS,
#        OPENADKIT_CLI (absolute launcher when running inside an integrator kit)

cell=${1:?usage: run_cell.sh <cell-json> <output-dir>}
out=${2:?usage: run_cell.sh <cell-json> <output-dir>}
cli=${OPENADKIT_CLI:-./openadkit}

field() { jq -r --arg key "$1" '.[$key] // ""' <<<"${cell}"; }
cell_name=$(field name)
deployment=$(field deployment)
distro=$(field distro)
node=$(field node)
kit=$(field kit)
platform=$(field platform)
fresh_topics=$(field fresh)
l1_check=$(field l1)
l2_check=$(field l2)
read -ra nodes <<<"$(field nodes)"
[ "${#nodes[@]}" -gt 0 ] || nodes=("${node}")

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# The cell's platform comes from the matrix; the host must be that machine,
# or the evidence would describe the wrong architecture.
case "$(uname -m)" in
    x86_64) host_platform=linux/amd64 ;;
    aarch64) host_platform=linux/arm64 ;;
    *) echo "unsupported evidence architecture: $(uname -m)" >&2; exit 1 ;;
esac
if [ "${platform}" != "${host_platform}" ]; then
    echo "cell ${cell_name} is planned for ${platform}, but this host is ${host_platform}" >&2
    exit 1
fi

mkdir -p "${out}"
# Keep run results with this cell's evidence instead of the runner's home.
export OPENADKIT_STATE_DIR="${out}/state"
# Read no host settings either: a site file, or an inherited kit selection,
# would change the deployment, its data, or its DDS settings under the cell.
export OPENADKIT_CONFIG_DIR="${out}/config"
unset OPENADKIT_KIT OPENADKIT_DELEGATED
mkdir -p "${OPENADKIT_CONFIG_DIR}"
scenario_output="${OPENADKIT_STATE_DIR}/${deployment}/output"
# A 4-vCPU runner cannot run Autoware main in real time: the ego drives late
# and the samples take three times as long as on 16 vCPUs, past the wall-clock
# timeout. Half speed gives Autoware the CPU a larger host has per simulated
# second, so the cell checks the scenarios rather than the runner's size.
if [ "${l2_check}" = scenario ]; then
    printf '%s\n' GLOBAL_REAL_TIME_FACTOR=0.5 GLOBAL_TIMEOUT=400 >"${OPENADKIT_CONFIG_DIR}/${deployment}.env"
fi

# Several nodes on one host: each gets its own project, logs and Zenoh endpoint.
split=false
[ "${#nodes[@]}" -gt 1 ] && split=true
projects=()
validation_files=()
for target_node in "${nodes[@]}"; do
    projects+=("openadkit-${deployment}${target_node:+-${target_node}}")
    suffix=""
    [ "${split}" = true ] && suffix="-${target_node}"
    validation_files+=("${out}/validate${suffix}.json")
done

api_container=autoware-api
api_services=${API_SERVICES:-/api/localization/initialize /api/routing/set_route_points /api/operation_mode/change_to_autonomous}
api_topics=${API_TOPICS:-/api/routing/state /api/localization/initialization_state /api/operation_mode/state}
# The first node listens on the base port; each later node listens on its own
# port and peers with the first.
zenoh_port=7447

node_cli() {
    local operation=$1 index=$2
    shift 2
    local target_node=${nodes[index]} args=() environment=()
    [ -n "${target_node}" ] && args=(--node "${target_node}")
    if [ "${split}" = true ] && { [ "${operation}" = run ] || [ "${operation}" = validate ]; }; then
        environment=("ZENOH_LISTEN=tcp/127.0.0.1:$((zenoh_port + index))")
        [ "${index}" -gt 0 ] && environment+=("ZENOH_PEER=tcp/127.0.0.1:${zenoh_port}")
    fi
    env "${environment[@]}" "${cli}" "${operation}" "${deployment}" "${args[@]}" "$@"
}

result="PASSED"
l0_ok=false
l1_ok=false
l2_ok="null"
ready_s="null"
arrival_s="null"
isolation="null"
scenario_json="null"
overlay_conformant=false

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
    for ((i=${#nodes[@]}-1; i>=0; i--)); do
        node_cli stop "${i}" >/dev/null 2>&1 || true
    done
}
trap cleanup EXIT

sample_memory &
sampler_pid=$!

# --- L0: manifest and compose validation -------------------------------------
l0_rc=0
for i in "${!nodes[@]}"; do
    node_cli validate "${i}" --ros-distro "${distro}" --json >"${validation_files[i]}" 2>"${validation_files[i]%.json}.log" || l0_rc=1
done
if [ "${l0_rc}" -eq 0 ]; then
    l0_ok=true
    overlay_conformant=$(jq -s 'all(.[]; .overlayConformant == true)' "${validation_files[@]}")
else
    result="FAILED"
fi

# --- L1: start the stack and check readiness ---------------------------------
if [ "${l0_rc}" -eq 0 ]; then
    run_start=$(date +%s)
    run_rc=0
    for i in "${!nodes[@]}"; do
        suffix=""
        [ "${split}" = true ] && suffix="-${nodes[i]}"
        # Nothing watches the visualizer here; its software-rendered RViz
        # would take CPU from Autoware on a 4-vCPU runner.
        node_cli run "${i}" --ros-distro "${distro}" --no-visualizer >"${out}/run${suffix}.log" 2>&1 || run_rc=1
    done

    if [ "${run_rc}" -eq 0 ] && docker inspect "${api_container}" >/dev/null 2>&1; then
        docker cp "${script_dir}/readiness.py" "${api_container}:/tmp/openadkit-readiness.py" >/dev/null 2>&1 || true
        # A 4-vCPU runner loads the Autoware containers in about five minutes.
        read_args=(--timeout 600 --output /tmp/readiness.json)
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

# Read every service's hook report; a typo may affect a package outside API.
if [ "${l0_ok}" = true ]; then
    report_args=()
    for name in "${projects[@]}"; do report_args+=(--project "${name}"); done
    if python3 "${script_dir}/overlay_conformance.py" "${report_args[@]}" --output "${out}/overlay.json" >"${out}/overlay.log" 2>&1; then
        runtime_conformant=$(jq -r '.overlayConformant == true' "${out}/overlay.json")
        [ "${runtime_conformant}" = true ] || overlay_conformant=false
    else
        overlay_conformant=false
    fi
fi

if [ "${l1_ok}" = true ] && [ "${l1_check}" = custom-kit ]; then
    docker cp "${script_dir}/custom_kit.py" "${api_container}:/tmp/openadkit-custom-kit.py" >/dev/null 2>&1
    if ! docker exec "${api_container}" bash -lc \
        "source /opt/ros/${distro}/setup.bash; source /opt/autoware/setup.sh; python3 /tmp/openadkit-custom-kit.py" >"${out}/custom-kit.log" 2>&1 \
        || [ "${overlay_conformant}" != true ]; then
        l1_ok=false
        result=FAILED
    fi
fi

# --- L2: end-to-end behaviour -------------------------------------------------
if [ "${l1_ok}" = true ]; then
    case "${l2_check}" in
        golden)
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
        scenario)
            # Three samples of up to GLOBAL_TIMEOUT each, after the readiness wait.
            ss_rc=$(timeout 1800 docker wait autoware-scenario-simulator 2>/dev/null || echo timeout)
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
                            -e CYCLONEDDS_NETWORK_INTERFACE=lo \
                            -e "ROS_DISTRO=${distro}" \
                            -v "${PWD}/deployments/shared/cyclonedds.xml:/etc/cyclonedds/cyclonedds.xml:ro" \
                            --entrypoint bash "${image}" -c \
                            'set -eo pipefail; source "/opt/ros/${ROS_DISTRO}/setup.bash";
                             topics=$(timeout 20 ros2 topic list);
                             printf "%s\n" "$topics" | awk '\''/^\/api\// { n++ } END { print n+0 }'\''' 2>/dev/null || echo failed
                    )
                else
                    isolation=failed
                fi
                [[ "${isolation}" =~ ^[0-9]+$ ]] && [ -f "${out}/scenario.json" ] &&
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
# null, like ready_s and arrival_s, when no container was ever sampled.
peak_mib=$(cat "${out}/.peak_mib" 2>/dev/null || echo null)
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
    --arg kit "${kit}" \
    --argjson l0 "${l0_ok}" \
    --argjson l1 "${l1_ok}" \
    --argjson l2 "${l2_ok}" \
    --argjson ready_s "${ready_s}" \
    --argjson arrival_s "${arrival_s}" \
    --argjson peak_mib "${peak_mib}" \
    --argjson scenario "${scenario_json}" \
    --argjson overlay_conformant "${overlay_conformant}" \
    '{
        schemaVersion: 1,
        name: $name,
        deployment: $deployment,
        distro: $distro,
        node: $node,
        platform: $platform,
        result: $result,
        build_tag: $build_tag,
        source_sha: $source_sha,
        kit: $kit,
        overlayConformant: $overlay_conformant,
        levels: {
            L0: {ok: $l0},
            L1: {ok: $l1, ready_s: $ready_s},
            L2: {ok: $l2, arrival_s: $arrival_s, scenario: $scenario}
        },
        metrics: {ready_s: $ready_s, arrival_s: $arrival_s, peak_mib: $peak_mib}
    }' >"${out}/cell.json"

echo "cell ${cell_name}: ${result} (L0=${l0_ok} L1=${l1_ok} L2=${l2_ok} isolation=${isolation})"
[ "${result}" = "PASSED" ]
