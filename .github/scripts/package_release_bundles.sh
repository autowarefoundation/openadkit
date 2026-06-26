#!/usr/bin/env bash
# Assemble and validate self-contained deployment bundles for a release.
set -euo pipefail

source_dir="${SOURCE_DIR:-src}"
install="${source_dir}/install.sh"
base_dir="${source_dir}/deployments/base"

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

  # Base-backed deployments ship a vendored base and a single merged env file.
  compose="staging/${name}/docker-compose.yaml"
  if [ -f "${compose}" ] && grep -q '\.\./base/docker-compose\.yaml' "${compose}"; then
    mkdir -p "staging/${name}/base"
    cp "${base_dir}/docker-compose.yaml" "staging/${name}/base/docker-compose.yaml"
    sed -i 's#\.\./base/docker-compose\.yaml#base/docker-compose.yaml#' "${compose}"
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

  tar -C staging -czf "dist/${name}.tar.gz" "${name}"
  echo "packaged dist/${name}.tar.gz"
done
