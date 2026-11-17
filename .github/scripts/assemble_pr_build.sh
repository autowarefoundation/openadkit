#!/usr/bin/env bash
# Make a pull request's build complete in the CI package, so the evidence and
# the release-like staging run on it unchanged: every inventory image gets
# <ci>:<target>-<distro>-<build_tag>. An image this run built (pushed as
# <target>-amd64-<distro>-<build_tag>) is used as is; any other one is copied,
# by digest and within the registry, from the base branch's latest build.
# Each also gets the moving <target>-<distro>-pr<number> tag that the cleanup
# deletes when the pull request closes.
#
# Env: CI_REPO, BUILD_TAG, RUN_ID, RUN_ATTEMPT, PR_NUMBER, BASE_METADATA
#      (the base build's build-metadata.json), INVENTORY (optional).
# Prints how many images this run built; 0 means there is nothing to verify.
set -euo pipefail

: "${CI_REPO:?CI_REPO is required}"
: "${BUILD_TAG:?BUILD_TAG is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${RUN_ATTEMPT:?RUN_ATTEMPT is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${BASE_METADATA:?BASE_METADATA is required}"
inventory=${INVENTORY:-.github/image-inventory.json}

exists() { docker buildx imagetools inspect "$1" >/dev/null 2>&1; }

built=0
while read -r target distro; do
    source=""
    # "Re-run failed jobs" keeps a successful job's tag from an earlier attempt.
    for ((attempt = RUN_ATTEMPT; attempt >= 1; attempt--)); do
        candidate="${CI_REPO}:${target}-amd64-${distro}-${RUN_ID}-${attempt}"
        if exists "${candidate}"; then
            source=${candidate}
            built=$((built + 1))
            break
        fi
    done
    if [ -z "${source}" ]; then
        source=$(jq -r --arg target "${target}" --arg distro "${distro}" \
            '.images[] | select(.target == $target and .ros_distro == $distro) | "\(.repo)@\(.digest)"' \
            "${BASE_METADATA}")
        [ -n "${source}" ] || { echo "The base build has no ${target}-${distro} image" >&2; exit 1; }
    fi
    echo "${target}-${distro}: ${source}" >&2
    docker buildx imagetools create \
        --tag "${CI_REPO}:${target}-${distro}-${BUILD_TAG}" \
        --tag "${CI_REPO}:${target}-${distro}-pr${PR_NUMBER}" \
        "${source}" >&2
done < <(jq -r '.ros_distros as $default | .images[] | select(.release != false) | .target as $target
    | (.ros_distros // $default)[] | "\($target) \(.)"' "${inventory}")
echo "${built}"
