#!/usr/bin/env bash
# shellcheck shell=bash
set -uo pipefail

# Run one evidence cell against a staged kit (run from the kit root):
#   L0: ./openadkit validate, in a kit for each of its deployments; in one cell
#       per distro, launch_arguments.py too
#   L1: ./openadkit run, which returns once the deployment's healthchecks pass
#   L2: the deployment's verify step (./openadkit run --verify): the drive to
#       the goal, or the scenario samples, plus a domain-isolation check when the
#       cell runs several roles on one host.
#   L3: for a kit with checks/dev_loop.sh, the development loop on the running
#       stack: change its package, build, restart, and see the change.
#   Then, as part of L1: no service turned unhealthy during the checks, and
#       the map service does once one of its nodes is killed, while it keeps running.
#
# The cell is one row of the evidence matrix (validation_matrix.py), which
# derives what to run and check from the manifests; this runner only executes
# it. Writes cell.json, per-step logs and metrics under the output directory,
# and collects container logs plus the scenario output when the cell fails.
#
# Usage: run_cell.sh <cell-json> <output-dir>
# Env:   BUILD_TAG, SOURCE_SHA,
#        OPENADKIT_CLI (absolute launcher when running inside a kit)

cell=${1:?usage: run_cell.sh <cell-json> <output-dir>}
out=${2:?usage: run_cell.sh <cell-json> <output-dir>}
cli=${OPENADKIT_CLI:-./openadkit}

field() { jq -r --arg key "$1" '.[$key] // ""' <<<"${cell}"; }
cell_name=$(field name)
deployment=$(field deployment)
distro=$(field distro)
role=$(field role)
kit=$(field kit)
backend=$(field backend)
platform=$(field platform)
verify=$(field verify)
# A verify step without a command waits for its service: the scenario run.
scenario=false
[ -n "${verify}" ] && ! jq -e 'has("command")' <<<"${verify}" >/dev/null && scenario=true
read -ra roles <<<"$(field roles)"
[ "${#roles[@]}" -gt 0 ] || roles=("${role}")

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
# Keep everything the CLI writes with this cell's evidence instead of the
# runner's home: results, run records and host settings, and the downloaded
# data (left out of the uploaded artifact). A host settings file, or an
# inherited kit selection, would change the deployment, its data, or its DDS
# settings under the cell.
export OPENADKIT_HOME="${out}/home"
# Cell logs show every docker command the CLI runs.
export OPENADKIT_VERBOSE=1
unset OPENADKIT_KIT OPENADKIT_DELEGATED
settings_dir="${OPENADKIT_HOME}/settings"
output_dir="${OPENADKIT_HOME}/output"
mkdir -p "${settings_dir}"
scenario_output="${output_dir}/${deployment}/results"
# A 4-vCPU runner cannot run Autoware main in real time: the ego drives late
# and the samples take three times as long as on 16 vCPUs, past the wall-clock
# timeout. Half speed gives Autoware the CPU a larger host has per simulated
# second, so the cell checks the scenarios rather than the runner's size.
if [ "${scenario}" = true ]; then
    printf '%s\n' GLOBAL_REAL_TIME_FACTOR=0.5 GLOBAL_TIMEOUT=400 >"${settings_dir}/${deployment}.env"
fi
# The same holds for a replayed recording: at a tenth of its speed sensing and
# perception keep up, and the rosbag waits longer for a slow start.
if [ "${deployment}" = logging-simulation ]; then
    printf '%s\n' ROSBAG_RATE=0.1 ROSBAG_READY_TIMEOUT=300 >"${settings_dir}/${deployment}.env"
fi

# Several roles on one host: each gets its own project, logs and Zenoh endpoint.
split=false
[ "${#roles[@]}" -gt 1 ] && split=true
projects=()
validation_files=()
for target_role in "${roles[@]}"; do
    projects+=("openadkit-${deployment}${target_role:+_${target_role}}")
    suffix=""
    [ "${split}" = true ] && suffix="-${target_role}"
    validation_files+=("${out}/validate${suffix}.json")
done

# The engine the stack runs on: Docker under Compose, or Podman under the AutoSD units.
engine=(docker)
[ "${backend}" = quadlet ] && engine=(sudo podman)
api_container=autoware-api
# The CLI's record of the run, written once the deployment is ready, with the
# verify step's result.
run_report="${output_dir}/${deployment}/results/run.json"
# The first role listens on the base port; each later role listens on its own
# port and peers with the first.
zenoh_port=7447

role_cli() {
    local operation=$1 index=$2
    shift 2
    local target_role=${roles[index]} args=("${deployment}") environment=()
    # stop acts on what runs here; it takes no deployment name.
    [ "${operation}" = stop ] && args=()
    [ -n "${target_role}" ] && args+=(--role "${target_role}")
    if [ "${split}" = true ] && { [ "${operation}" = run ] || [ "${operation}" = validate ]; }; then
        environment=("ZENOH_LISTEN=tcp/127.0.0.1:$((zenoh_port + index))")
        [ "${index}" -gt 0 ] && environment+=("ZENOH_PEER=tcp/127.0.0.1:${zenoh_port}")
    fi
    env "${environment[@]}" "${cli}" "${operation}" "${args[@]}" "$@"
}

# Generate the AutoSD units, install them as an image would and start them.
start_quadlet() {
    local tree="${out}/quadlet" units
    "${cli}" fetch "${deployment}" || return 1
    "${cli}" config "${deployment}" --ros-distro "${distro}" |
        python3 "${script_dir}/../../../platforms/autosd/quadlet.py" --output "${tree}" --without visualizer || return 1
    # Only the two trees, and without their owner or modes: cp -a would give
    # the runner's /, /etc and /usr those of the generated tree.
    sudo mkdir -p /etc/containers/systemd /usr/share/openadkit || return 1
    sudo cp -r "${tree}/rootfs/etc/containers/systemd/." /etc/containers/systemd/ || return 1
    sudo cp -r "${tree}/rootfs/usr/share/openadkit/." /usr/share/openadkit/ || return 1
    units=$(basename -a -s .container "${tree}"/rootfs/etc/containers/systemd/*.container)
    # The map is in the tree too; keep it out of the cell's artifacts.
    rm -rf "${tree}"
    sudo systemctl daemon-reload || return 1
    # shellcheck disable=SC2086
    sudo systemctl start ${units}
}

result="PASSED"
l0_ok=false
l1_ok=false
l2_ok="null"
l3_ok="null"
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
        # In the background, so cleanup stops the sampler at once; away from
        # the cell's output, which a reader waits on until it closes.
        sleep 2 >/dev/null 2>&1 & wait $!
    done
}

cleanup() {
    kill "${sampler_pid:-}" 2>/dev/null
    wait "${sampler_pid:-}" 2>/dev/null
    [ "${backend}" = quadlet ] && sudo systemctl stop 'autoware-*' >/dev/null 2>&1
    for ((i=${#roles[@]}-1; i>=0; i--)); do
        role_cli stop "${i}" >/dev/null 2>&1 || true
    done
}
trap cleanup EXIT

sample_memory &
sampler_pid=$!

# --- L0: manifest and compose validation -------------------------------------
l0_rc=0
for i in "${!roles[@]}"; do
    role_cli validate "${i}" --ros-distro "${distro}" --json >"${validation_files[i]}" 2>"${validation_files[i]%.json}.log" || l0_rc=1
done
# A kit's other deployments share its files: they must validate too.
if [ -n "${kit}" ]; then
    "${cli}" validate --ros-distro "${distro}" >"${out}/validate-kit.log" 2>&1 || l0_rc=1
fi
# One cell per distro also checks that the images' launch files read every
# launch argument the catalog deployments pass.
if [ "$(field launch_arguments)" = all ]; then
    python3 "${script_dir}/launch_arguments.py" "${cli}" "${distro}" 2>&1 | tee "${out}/launch-arguments.log" || l0_rc=1
fi
if [ "${l0_rc}" -eq 0 ]; then
    l0_ok=true
else
    result="FAILED"
fi

# --- L1: start the stack; run returns once its healthchecks pass ------------
# --- L2: the deployment's verify step ----------------------------------------
# One host runs the whole graph with `run --verify`. Split roles start
# without it: the bridge allowlist needs the scenario graph while it runs,
# so the cell waits for the scenario itself. Quadlet units start under
# systemd and run the same verify command with Podman.
in_api() {
    # shellcheck disable=SC2016 # Expanded in the container.
    "${engine[@]}" exec "${api_container}" bash -c \
        'source "/opt/ros/${ROS_DISTRO}/setup.bash"; source /opt/autoware/setup.bash; exec "$@"' bash "$@"
}

if [ "${l0_rc}" -eq 0 ]; then
    run_start=$(date +%s)
    if [ "${backend}" = quadlet ]; then
        if start_quadlet >"${out}/run.log" 2>&1; then
            # The api unit's healthcheck is the deployment's readiness.
            deadline=$(( $(date +%s) + 900 ))
            until [ "$(sudo podman inspect -f '{{.State.Health.Status}}' "${api_container}" 2>/dev/null)" = healthy ]; do
                [ "$(date +%s)" -lt "${deadline}" ] || break
                sleep 5
            done
            [ "$(sudo podman inspect -f '{{.State.Health.Status}}' "${api_container}" 2>/dev/null)" = healthy ] && l1_ok=true
        fi
        ready_s=$(( $(date +%s) - run_start ))
        if [ "${l1_ok}" = true ] && [ -n "${verify}" ]; then
            mapfile -t verify_command < <(jq -r '.command[]' <<<"${verify}")
            verify_start=$(date +%s)
            in_api "${verify_command[@]}" >"${out}/verify.log" 2>&1
            verify_rc=$?
            arrival_s=$(( $(date +%s) - verify_start ))
            if [ "${verify_rc}" -eq 0 ]; then l2_ok=true; else l2_ok=false; fi
        fi
    elif [ "${split}" = true ]; then
        run_rc=0
        for i in "${!roles[@]}"; do
            # Nothing watches the visualizer here; its software-rendered RViz
            # would take CPU from Autoware on a 4-vCPU runner.
            role_cli run "${i}" --ros-distro "${distro}" --no-visualizer >"${out}/run-${roles[i]}.log" 2>&1 || run_rc=1
        done
        ready_s=$(( $(date +%s) - run_start ))
        [ "${run_rc}" -eq 0 ] && l1_ok=true
    else
        verify_args=()
        [ -n "${verify}" ] && verify_args=(--verify)
        role_cli run 0 --ros-distro "${distro}" --no-visualizer "${verify_args[@]}" >"${out}/run.log" 2>&1
        run_rc=$?
        if [ -f "${run_report}" ]; then
            cp "${run_report}" "${out}/run.json"
            l1_ok=true
            ready_s=$(jq '.readySeconds | floor' "${run_report}")
            if [ -n "${verify}" ]; then
                arrival_s=$(jq '.verify.seconds // null | if . then floor else . end' "${run_report}")
                if [ "$(jq -r '.verify.result // empty' "${run_report}")" = PASSED ]; then l2_ok=true; else l2_ok=false; fi
            fi
        fi
        [ "${run_rc}" -eq 0 ] || [ -n "${verify}" ] || l1_ok=false
    fi
    [ "${l1_ok}" = true ] || result="FAILED"
fi

if [ "${l1_ok}" = true ] && [ "${split}" = true ] && [ "${scenario}" = true ]; then
    # The scenario graph is up once its /clock reaches the Autoware role.
    deadline=$(( $(date +%s) + 600 ))
    until in_api python3 /openadkit/checks/readiness.py --fresh /clock >>"${out}/clock.log" 2>&1; do
        [ "$(date +%s)" -lt "${deadline}" ] || { l1_ok=false; result=FAILED; break; }
        sleep 5
    done
fi

# Every topic the split bridge allows must exist in one of the two graphs: an
# Autoware rename would otherwise stop it crossing without any error.
if [ "${l1_ok}" = true ] && [ "${split}" = true ] && [ "${scenario}" = true ]; then
    list_topics='timeout 60 ros2 topic list --no-daemon --spin-time 5'
    docker exec "${api_container}" bash -lc \
        "source /opt/ros/${distro}/setup.bash; source /opt/autoware/setup.sh; ${list_topics}" \
        >"${out}/topics-autoware.txt" 2>/dev/null
    docker exec autoware-scenario-simulator bash -lc \
        "source /opt/ros/${distro}/setup.bash; ${list_topics}" \
        >"${out}/topics-scenario.txt" 2>/dev/null
    if ! python3 "${script_dir}/allowlist.py" --config "deployments/${deployment}/config/zenoh.json5" \
        --topics "${out}/topics-autoware.txt" --topics "${out}/topics-scenario.txt" >"${out}/allowlist.log" 2>&1; then
        l1_ok=false
        result=FAILED
    fi
fi

# The scenario's own result, its metrics and, across split roles, isolation.
if [ "${l1_ok}" = true ] && [ "${scenario}" = true ]; then
    ss_rc=0
    if [ "${split}" = true ]; then
        # Three samples of up to GLOBAL_TIMEOUT each, after readiness.
        ss_rc=$(timeout 1800 docker wait autoware-scenario-simulator 2>/dev/null || echo timeout)
    elif [ "${l2_ok}" != true ]; then
        ss_rc=failed
    fi
    docker logs autoware-scenario-simulator >"${out}/scenario.log" 2>&1 || true
    python3 "${script_dir}/scenario_metrics.py" \
        --output-dir "${scenario_output}" \
        --log "${out}/scenario.log" \
        --json "${out}/scenario.json" >"${out}/scenario-metrics.log" 2>&1
    metrics_rc=$?

    if [ "${split}" = true ]; then
        # Isolation: without the scenario role's bridge, domain 2 must
        # not see the autoware role's /api topics.
        bridge=$(
            docker ps -q \
                --filter "label=com.docker.compose.project=openadkit-${deployment}_scenario" |
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
    fi
fi
[ "${l2_ok}" = false ] && result="FAILED"

# --- L3: the development loop of a kit, on the stack L2 checked --------------
if [ "${l2_ok}" = true ] && [ -n "${kit}" ] && [ -f checks/dev_loop.sh ]; then
    if bash checks/dev_loop.sh "${cli}" "${distro}" >"${out}/dev-loop.log" 2>&1; then
        l3_ok=true
    else
        l3_ok=false
        result="FAILED"
    fi
fi

# --- L1, at the end: no node died, and a node that dies shows ----------------
# A service turns unhealthy when one of its nodes dies
# (components/shared/entrypoint/health). None may have during the checks above.
# Then one node of the map is killed: the map must turn unhealthy and keep
# running. One only: a launch whose processes are all gone exits.
container_health() {
    local name ids=() format='{{.Name}} {{with index .State "Health"}}{{.Status}}{{else}}none{{end}}'
    if [ "${backend}" = quadlet ]; then
        format='{{.Name}} {{.State.Health.Status}}'
        mapfile -t ids < <(sudo podman ps -q --filter name=autoware-)
    else
        for name in "${projects[@]}"; do
            mapfile -t -O "${#ids[@]}" ids < <(docker ps -q --filter "label=com.docker.compose.project=${name}")
        done
    fi
    [ "${#ids[@]}" -eq 0 ] || "${engine[@]}" inspect -f "${format}" "${ids[@]}"
}
map_state() {
    "${engine[@]}" inspect -f '{{.State.Status}} {{.State.Health.Status}}' autoware-map 2>/dev/null
}

if [ "${l1_ok}" = true ]; then
    {
        echo "after the checks:"
        container_health | tee "${out}/.health"
        if grep -q ' unhealthy$' "${out}/.health"; then
            l1_ok=false
        fi
        rm -f "${out}/.health"
        # shellcheck disable=SC2016 # Expanded in the container.
        "${engine[@]}" exec autoware-map bash -c \
            'pkill -KILL -o -P "$(pgrep -f "[p]ython3 .*/ros2 launch .*component:=component_map")"'
        deadline=$(( $(date +%s) + 60 ))
        until [ "$(map_state)" = "running unhealthy" ] || [ "$(date +%s)" -ge "${deadline}" ]; do
            sleep 1
        done
        echo "after killing a node of the map: $(map_state)"
        [ "$(map_state)" = "running unhealthy" ] || l1_ok=false
    } >"${out}/health.log" 2>&1
    [ "${l1_ok}" = true ] || result="FAILED"
fi

# --- artifacts ---------------------------------------------------------------
# null, like ready_s and arrival_s, when no container was ever sampled.
peak_mib=$(cat "${out}/.peak_mib" 2>/dev/null || echo null)
rm -f "${out}/.peak_mib"

if [ "${result}" != "PASSED" ]; then
    mkdir -p "${out}/logs"
    # shellcheck disable=SC2024 # The cell's own log file, written as the cell's user.
    [ "${backend}" = quadlet ] && sudo journalctl --no-pager -u 'autoware-*' >"${out}/logs/units.log" 2>&1
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
    --arg role "${role}" \
    --arg platform "${platform}" \
    --arg result "${result}" \
    --arg build_tag "${BUILD_TAG:-unknown}" \
    --arg source_sha "${SOURCE_SHA:-unknown}" \
    --arg kit "${kit}" \
    --argjson l0 "${l0_ok}" \
    --argjson l1 "${l1_ok}" \
    --argjson l2 "${l2_ok}" \
    --argjson l3 "${l3_ok}" \
    --argjson ready_s "${ready_s}" \
    --argjson arrival_s "${arrival_s}" \
    --argjson peak_mib "${peak_mib}" \
    --argjson scenario "${scenario_json}" \
    '{
        schemaVersion: 1,
        name: $name,
        deployment: $deployment,
        distro: $distro,
        role: $role,
        platform: $platform,
        result: $result,
        build_tag: $build_tag,
        source_sha: $source_sha,
        kit: $kit,
        levels: {
            L0: {ok: $l0},
            L1: {ok: $l1, ready_s: $ready_s},
            L2: {ok: $l2, arrival_s: $arrival_s, scenario: $scenario},
            L3: {ok: $l3}
        },
        metrics: {ready_s: $ready_s, arrival_s: $arrival_s, peak_mib: $peak_mib}
    }' >"${out}/cell.json"

echo "cell ${cell_name}: ${result} (L0=${l0_ok} L1=${l1_ok} L2=${l2_ok} L3=${l3_ok} isolation=${isolation})"
[ "${result}" = "PASSED" ]
