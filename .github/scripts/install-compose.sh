#!/usr/bin/env bash
# Install the latest Docker Compose from the official GitHub release.
#
# The ubuntu-latest / ubuntu-22.04 runners ship an older compose plugin that
# rejects service overrides after `include:`. This script downloads the latest
# release, verifies its SHA-256 checksum, and installs it into
# ~/.docker/cli-plugins/.
#
# Required tools: curl, jq, awk, sha256sum, uname
set -euo pipefail

mkdir -p ~/.docker/cli-plugins

# Use GITHUB_TOKEN if available to avoid GitHub API rate limiting.
token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"

# Pin the Compose version for reproducible builds. Override COMPOSE_VERSION to
# bump deliberately, or set it to "latest" to resolve the newest release. The
# per-release SHA-256 checksum is still verified below regardless of the source.
compose_version="${COMPOSE_VERSION:-v5.3.1}"
if [ "${compose_version}" = "latest" ]; then
  latest_tag=$(curl -fsSL --retry 3 --retry-delay 1 \
    ${token:+-H "Authorization: token ${token}"} \
    https://api.github.com/repos/docker/compose/releases/latest | jq -r '.tag_name')
else
  latest_tag="${compose_version}"
fi

# Map runner architecture to Compose release artifact name.
arch=$(uname -m)
case "${arch}" in
  x86_64)  compose_arch="x86_64" ;;
  aarch64) compose_arch="aarch64" ;;
  *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;;
esac

base_url="https://github.com/docker/compose/releases/download/${latest_tag}"
bin_name="docker-compose-linux-${compose_arch}"
bin_path="${HOME}/.docker/cli-plugins/docker-compose"

curl -fsSL --retry 3 --retry-delay 1 \
  "${base_url}/${bin_name}" -o "${bin_path}"
curl -fsSL --retry 3 --retry-delay 1 \
  "${base_url}/${bin_name}.sha256" -o "${bin_path}.sha256"

# Verify checksum: extract expected hash and compare.
expected=$(awk '{print $1}' "${bin_path}.sha256")
actual=$(sha256sum "${bin_path}" | awk '{print $1}')
if [ "${expected}" != "${actual}" ]; then
  echo "SHA-256 checksum mismatch for ${bin_name}" >&2
  echo "  expected: ${expected}" >&2
  echo "  actual:   ${actual}" >&2
  exit 1
fi

chmod +x "${bin_path}"
docker compose version
