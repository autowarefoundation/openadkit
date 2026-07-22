#!/usr/bin/env bash
# Assemble and validate self-contained deployment bundles for a release.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/registry_lookup.sh
# shellcheck disable=SC1091
source "${script_dir}/registry_lookup.sh"

source_dir="${SOURCE_DIR:-src}"
install="${source_dir}/install.sh"
base_dir="${source_dir}/deployments/base"
image_prefix_component="${IMAGE_PREFIX_COMPONENT:-ghcr.io/autowarefoundation/openadkit}"
build_metadata_file="${BUILD_METADATA_FILE:-release-input/build/build-metadata.json}"

third_party_digest() {
  local ref="$1"
  if [ -n "${THIRD_PARTY_IMAGE_DIGESTS_JSON:-}" ]; then
    jq -er --arg ref "${ref}" '.[$ref] | select(test("^sha256:[0-9a-f]{64}$"))' \
      <<<"${THIRD_PARTY_IMAGE_DIGESTS_JSON}"
  else
    registry_manifest_digest "${ref}"
  fi
}

mkdir -p dist staging
for entry in \
  "planning-simulation:${source_dir}/deployments/planning-simulation" \
  "scenario-simulation:${source_dir}/deployments/scenario-simulation" \
  "logging-simulation:${source_dir}/deployments/logging-simulation" \
  "carla-simulation:${source_dir}/deployments/carla-simulation" \
  "zenoh-bridge:${source_dir}/deployments/zenoh-bridge"; do
  name="${entry%%:*}"
  dir="${entry#*:}"
  rm -rf "staging/${name}"
  cp -a "${dir}" "staging/${name}"

  if [ "${name}" = "zenoh-bridge" ] && [ -f "staging/${name}/.env.example" ]; then
    cp "staging/${name}/.env.example" "staging/${name}/.env"
  fi

  # carla-simulation downloads its own assets via start-carla-e2e-demo.sh.
  if [ "${name}" != "carla-simulation" ]; then
    cp "${install}" "staging/${name}/install.sh"
    chmod +x "staging/${name}/install.sh"
  fi

  # Base-backed deployments ship a vendored base and a single merged env file.
  compose="staging/${name}/docker-compose.yaml"
  if [ -f "${compose}" ] && grep -q '\.\./base/docker-compose\.yaml' "${compose}"; then
    mkdir -p "staging/${name}/base"
    cp "${base_dir}/docker-compose.yaml" "staging/${name}/base/docker-compose.yaml"
    cp "${base_dir}/cyclonedds.xml" "staging/${name}/base/cyclonedds.xml"
    sed -i 's#\.\./base/#./base/#' "${compose}"
    env_file="staging/${name}/${name}.env"
    if [ -f "${env_file}" ]; then
      tmp="$(mktemp)"
      tmp_base="$(mktemp)"
      cp "${base_dir}/base.env" "${tmp_base}"
      if [ -s "${tmp_base}" ] && [ "$(tail -c 1 "${tmp_base}" | wc -l)" -eq 0 ]; then
        printf '\n' >> "${tmp_base}"
      fi
      cat "${tmp_base}" "${env_file}" > "${tmp}"
      rm -f "${tmp_base}"
      mv "${tmp}" "${env_file}"
    fi
  fi

  # Keep the readable release tag, but bind it to the exact validated digest so
  # a downloaded bundle cannot change if a registry credential later moves it.
  if [ -n "${VERSION:-}" ] && [ -n "${DEFAULT_ROS_DISTRO:-}" ]; then
    [ -f "${build_metadata_file}" ] || {
      echo "Validated build metadata not found: ${build_metadata_file}" >&2
      exit 1
    }
    bundle_ros_distro="${DEFAULT_ROS_DISTRO}"
    if [ "${name}" = "carla-simulation" ]; then
      bundle_ros_distro=humble
    fi
    bundle_files=(
      "staging/${name}/docker-compose.yaml" \
      "staging/${name}/docker-compose."*.yaml \
      "staging/${name}/base/docker-compose.yaml" \
      "staging/${name}/${name}.env" \
      "staging/${name}/${name}."*.env \
      "staging/${name}/.env"
    )
    echo "Pinning Open AD Kit image refs to ${bundle_ros_distro}-${VERSION} and validated digests"
    while IFS= read -r target; do
      [ -n "${target}" ] || continue
      matches=$(jq -c \
        --arg repo "${image_prefix_component}" \
        --arg target "${target}" \
        --arg distro "${bundle_ros_distro}" \
        '[.images[] | select(.repo == $repo and .target == $target and .ros_distro == $distro)]' \
        "${build_metadata_file}")
      [ "$(jq 'length' <<<"${matches}")" -eq 1 ] || {
        echo "Expected one validated digest for ${image_prefix_component}:${target}-${bundle_ros_distro}, found $(jq 'length' <<<"${matches}")" >&2
        exit 1
      }
      digest=$(jq -r '.[0].digest | select(test("^sha256:[0-9a-f]{64}$"))' <<<"${matches}")
      [ -n "${digest}" ] || {
        echo "Invalid validated digest for ${target}-${bundle_ros_distro}" >&2
        exit 1
      }
      for f in "${bundle_files[@]}"; do
        [ -f "${f}" ] || continue
        sed -i -E "s#ghcr\.io/autowarefoundation/openadkit:${target}([^a-z-]|$)#${image_prefix_component}:${target}-${bundle_ros_distro}-${VERSION}@${digest}\1#g" "${f}"
        if grep -Eq "ghcr\.io/autowarefoundation/openadkit:${target}([^a-z-]|$)" "${f}"; then
          echo "Unpinned Open AD Kit image reference remains in ${f}" >&2
          exit 1
        fi
      done
    done < <(
      for f in "${bundle_files[@]}"; do
        [ -f "${f}" ] || continue
        grep -hoE 'ghcr\.io/autowarefoundation/openadkit:[a-z-]+' "${f}" || true
      done | cut -d: -f2 | sort -u
    )
  else
    echo "VERSION/DEFAULT_ROS_DISTRO not set; skipping image pinning"
  fi

  # Resolve every literal third-party image used by the deployment. Keeping
  # the human-readable tag before @sha256 documents the selected upstream
  # version while making pulls immutable.
  for ref in \
    ghcr.io/autowarefoundation/autoware:universe \
    eclipse/zenoh-bridge-ros2dds:latest \
    ghcr.io/evshary/autoware_manual_control:latest \
    ghcr.io/tier4/scenario_simulator_v2:humble-25.0.20-runtime \
    carlasim/carla:0.9.16 \
    busybox:1.36.1; do
    matching_files=()
    while IFS= read -r -d '' candidate; do
      # Skip files where this ref is already digest-pinned (e.g. source compose
      # defaults that ship "<tag>@sha256:..."), so pinning stays idempotent and
      # never produces a malformed "<tag>@sha256:...@sha256:..." reference.
      if grep -Fq "${ref}@sha256:" "${candidate}"; then
        continue
      fi
      if grep -Fq "${ref}" "${candidate}"; then
        matching_files+=("${candidate}")
      fi
    done < <(find "staging/${name}" -type f \( -name '*.yaml' -o -name '*.env' -o -name '.env' \) -print0)
    [ "${#matching_files[@]}" -gt 0 ] || continue
    digest=$(third_party_digest "${ref}")
    echo "Pinning ${ref}@${digest}"
    sed -i "s#${ref}#${ref}@${digest}#g" "${matching_files[@]}"
  done

  env_file="staging/${name}/${name}.env"
  if [ -f "${env_file}" ]; then
    echo "::group::validate ${name}"
    if (cd "staging/${name}" && docker compose --env-file "${name}.env" config -q); then
      echo "ok: ${name}"
    else
      echo "::error::invalid docker compose config in staging/${name}"
      exit 1
    fi
    for variant_path in "staging/${name}/${name}."*.env; do
      [ -f "${variant_path}" ] || continue
      variant_env="$(basename "${variant_path}")"
      variant="${variant_env#"${name}".}"
      variant="${variant%.env}"
      variant_compose="docker-compose.${variant}.yaml"
      [ -f "staging/${name}/${variant_compose}" ] || continue
      if (cd "staging/${name}" && docker compose --env-file "${name}.env" --env-file "${variant_env}" -f docker-compose.yaml -f "${variant_compose}" config -q); then
        echo "ok: ${name} ${variant}"
      else
        echo "::error::invalid docker compose config for ${variant} variant in staging/${name}"
        exit 1
      fi
    done
    echo "::endgroup::"
  elif [ "${name}" = "zenoh-bridge" ] && [ -f "staging/${name}/.env" ]; then
    echo "::group::validate ${name}"
    if (cd "staging/${name}" && REMOTE_PASSWORD=ci-validate docker compose --env-file .env config -q); then
      echo "ok: ${name}"
    else
      echo "::error::invalid docker compose config in staging/${name}"
      exit 1
    fi
    echo "::endgroup::"
  fi

  # Normalize archive metadata so an idempotent release rerun produces the
  # exact same bytes instead of silently replacing historical assets.
  tar \
    --sort=name \
    --mtime='@0' \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -C staging \
    -czf "dist/${name}.tar.gz" \
    "${name}"
  echo "packaged dist/${name}.tar.gz"
done
