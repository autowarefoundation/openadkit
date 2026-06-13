#!/usr/bin/env bash
# Fetch sample map/rosbag data for an Open AD Kit deployment.
#
# Every deployment mounts its data from a host path; this script populates that
# path (default: ~/autoware_map). Sample maps/rosbags come from Autoware's public
# S3; the scenario map (kashiwanoha) comes from the upstream tier4 repository.
set -euo pipefail

S3_BASE="https://autoware-files.s3.us-west-2.amazonaws.com"
TIER4_TAG="25.0.20" # matches ghcr.io/tier4/scenario_simulator_v2:humble-25.0.20-runtime
TIER4_RAW="https://raw.githubusercontent.com/tier4/scenario_simulator_v2/${TIER4_TAG}/map/kashiwanoha_map/map"

# Under sudo, HOME is root's; the data must land in the invoking user's home,
# since that is what the deployments mount.
if [ -n "${SUDO_USER:-}" ]; then
  USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
else
  USER_HOME="$HOME"
fi
MAP_ROOT="${AUTOWARE_MAP_DIR:-${USER_HOME}/autoware_map}"

FORCE=0
TMP=""

cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

err() { echo "ERROR: $*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: ./fetch-sample-data.sh <deployment> [--force]

Downloads sample data into ${MAP_ROOT} (the directory mounted by the deployment).

Deployments:
  planning-simulation   sample-map-planning            (Autoware S3)
  logging-simulation    sample-map-rosbag, sample-rosbag (Autoware S3)
  scenario-simulation   kashiwanoha_map                (tier4 scenario_simulator_v2)
  zenoh-bridge          kashiwanoha_map                (tier4 scenario_simulator_v2)

Options:
  --force   Re-download even if the target directory already exists.
  -h, --help
EOF
}

sha256_verify() { # <file> <expected-sum>
  local got
  if command -v sha256sum >/dev/null 2>&1; then
    got="$(sha256sum "$1" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    got="$(shasum -a 256 "$1" | awk '{print $1}')"
  else
    err "need 'sha256sum' or 'shasum' to verify downloads"
  fi
  [ "$got" = "$2" ] || err "checksum mismatch for $1 (expected $2, got $got)"
}

already_present() { # <target-dir> <name> — true when the target exists and --force is off
  if [ "$FORCE" -eq 0 ] && [ -d "$1" ]; then
    echo "OK  $2 already present at $1 (use --force to re-download)"
    return 0
  fi
  return 1
}

fetch_zip() { # <url> <sha256> <dirname>
  local url="$1" sum="$2" name="$3" target="${MAP_ROOT}/$3"
  already_present "$target" "$name" && return 0
  command -v unzip >/dev/null 2>&1 || err "'unzip' is required"
  echo "==> downloading ${name} ..."
  curl -fL --retry 3 -o "${TMP}/${name}.zip" "$url"
  sha256_verify "${TMP}/${name}.zip" "$sum"
  mkdir -p "$MAP_ROOT"
  unzip -oq "${TMP}/${name}.zip" -d "$MAP_ROOT"
  echo "OK  ${name} -> ${target}"
}

fetch_kashiwanoha() {
  local target="${MAP_ROOT}/kashiwanoha_map"
  already_present "$target" "kashiwanoha_map" && return 0
  echo "==> downloading kashiwanoha_map (tier4 scenario_simulator_v2 @ ${TIER4_TAG}) ..."
  local stage="${TMP}/kashiwanoha_map"
  mkdir -p "$stage"
  # Single curl invocation: reuses one connection for all five files.
  local curl_args=() f
  for f in lanelet2_map.osm pointcloud_map.pcd global_map_center.pcd.yaml \
           lanelet2_map_provider.osm.yaml map.map_publisher.yaml; do
    curl_args+=(-o "${stage}/${f}" "${TIER4_RAW}/${f}")
  done
  curl -fL --retry 3 "${curl_args[@]}"
  # Move into place only after all files downloaded (avoid a half-populated dir).
  mkdir -p "$MAP_ROOT"
  rm -rf "$target"
  mv "$stage" "$target"
  echo "OK  kashiwanoha_map -> ${target}"
}

main() {
  local name=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--help) usage; exit 0 ;;
      --force) FORCE=1; shift ;;
      -*) err "unknown option: $1 (see --help)" ;;
      *) [ -z "$name" ] || err "unexpected argument: $1"; name="$1"; shift ;;
    esac
  done
  [ -n "$name" ] || { usage; exit 1; }
  command -v curl >/dev/null 2>&1 || err "'curl' is required"
  TMP="$(mktemp -d)"

  case "$name" in
    planning-simulation)
      fetch_zip "${S3_BASE}/maps/demos/sample-map-planning.zip" \
        "5536fce7bb8db7688fdf94ec004118b898637ad0d5b6175108b10989dd6e93b9" "sample-map-planning"
      ;;
    logging-simulation)
      fetch_zip "${S3_BASE}/maps/demos/sample-map-rosbag.zip" \
        "07e2da0b0bf12e2324f7083c2ce5556fb8044c50cef1da6428ab9084c3903bc8" "sample-map-rosbag"
      fetch_zip "${S3_BASE}/recordings/bags/demos/sample-rosbag.zip" \
        "5f9d36353393b3d249212153c19049822b1298db56512aa045b4f7f6fc37cf88" "sample-rosbag"
      # Perception models are mounted from ~/autoware_data; ensure the host dir
      # exists (Docker would otherwise create it as root). Populate it with
      # `setup.sh --download-artifacts`.
      mkdir -p "${USER_HOME}/autoware_data"
      if [ -n "${SUDO_USER:-}" ]; then
        chown "${SUDO_USER}:" "${USER_HOME}/autoware_data"
      fi
      echo "NOTE: logging-simulation also needs Autoware perception artifacts in ~/autoware_data"
      echo "      (download them with: setup.sh --download-artifacts)."
      ;;
    scenario-simulation|zenoh-bridge)
      fetch_kashiwanoha
      ;;
    *)
      err "unknown deployment '${name}' (see --help)"
      ;;
  esac
  echo "Done. Data is under ${MAP_ROOT}."
}

main "$@"
