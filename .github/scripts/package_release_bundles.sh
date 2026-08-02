#!/usr/bin/env bash
# Assemble and validate self-contained deployment bundles for a release.
set -euo pipefail

source_dir="${SOURCE_DIR:-src}"
install="${source_dir}/install.sh"
base_dir="${source_dir}/deployments/base"
image_prefix_component="${IMAGE_PREFIX_COMPONENT:-ghcr.io/autowarefoundation/openadkit}"
build_metadata_file="${BUILD_METADATA_FILE:-release-input/build/build-metadata.json}"

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

  # carla-simulation downloads its own assets via start-carla-e2e-demo.sh.
  if [ "${name}" != "carla-simulation" ]; then
    cp "${install}" "staging/${name}/install.sh"
    chmod +x "staging/${name}/install.sh"
  fi

  # Base-backed deployments ship the complete base beside their config.env.
  compose="staging/${name}/docker-compose.yaml"
  if [ -f "${compose}" ] && grep -q '\.\./base/docker-compose\.yaml' "${compose}"; then
    mkdir -p "staging/${name}/base"
    cp -a "${base_dir}/." "staging/${name}/base/"
    sed -i 's#\.\./base/#./base/#' "${compose}"
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
      "staging/${name}/config.env"
    )
    echo "Pinning Open AD Kit image refs to ${bundle_ros_distro}-${VERSION} and validated digests"
    while IFS= read -r target; do
      [ -n "${target}" ] || continue
      source_pattern="ghcr\\.io/autowarefoundation/openadkit:${target}(-(amd64|arm64))?(-(humble|jazzy))?([^a-z0-9-]|$)"
      present=false
      for f in "${bundle_files[@]}"; do
        [ -f "${f}" ] || continue
        if grep -Eq "${source_pattern}" "${f}"; then
          present=true
          break
        fi
      done
      [ "${present}" = true ] || continue
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
        sed -i -E "s#${source_pattern}#${image_prefix_component}:${target}-${bundle_ros_distro}-${VERSION}@${digest}\\5#g" "${f}"
        if grep -Eq "${source_pattern}" "${f}"; then
          echo "Unpinned Open AD Kit image reference remains in ${f}" >&2
          exit 1
        fi
      done
    done < <(
      jq -r \
        --arg repo "${image_prefix_component}" \
        --arg distro "${bundle_ros_distro}" \
        '.images[] | select(.repo == $repo and .ros_distro == $distro) | .target' \
        "${build_metadata_file}" | sort -r
    )
  else
    echo "VERSION/DEFAULT_ROS_DISTRO not set; skipping image pinning"
  fi

  # Source deployments must pin every third-party image. Resolving mutable tags
  # during packaging would make a rerun of the same release non-reproducible.
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
    done < <(find "staging/${name}" -type f \( -name '*.yaml' -o -name '*.env' \) -print0)
    [ "${#matching_files[@]}" -gt 0 ] || continue
    echo "Unpinned third-party image reference ${ref} in ${matching_files[*]}" >&2
    exit 1
  done

  env_file="staging/${name}/config.env"
  if [ -f "${env_file}" ]; then
    echo "::group::validate ${name}"
    if (cd "staging/${name}" && docker compose --env-file config.env config -q); then
      echo "ok: ${name}"
    else
      echo "::error::invalid docker compose config in staging/${name}"
      exit 1
    fi
    for variant_path in "staging/${name}/docker-compose."*.yaml; do
      [ -f "${variant_path}" ] || continue
      variant_compose="$(basename "${variant_path}")"
      variant="${variant_compose#docker-compose.}"
      variant="${variant%.yaml}"
      if (cd "staging/${name}" && docker compose --env-file config.env -f docker-compose.yaml -f "${variant_compose}" config -q); then
        echo "ok: ${name} ${variant}"
      else
        echo "::error::invalid docker compose config for ${variant} variant in staging/${name}"
        exit 1
      fi
    done
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
