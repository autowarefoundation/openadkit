#!/usr/bin/env bash
# Prune prior-lineage BuildKit cache mount entries from the GitHub Actions cache.
#
# KEEP_KEY is written by the actions/cache POST step, which runs after this
# script, so it is never present here: this prune only removes prior-lineage
# caches. The size check refreshes an oversized cache on a same-SHA rerun (when
# KEEP_KEY already exists). --limit caps recovery if a lineage ever exceeds it;
# steady state keeps a single entry.
#
# Required env: GH_TOKEN, CACHE_KEY_PREFIX, KEEP_KEY, MAX_GB
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${CACHE_KEY_PREFIX:?CACHE_KEY_PREFIX is required}"
: "${KEEP_KEY:?KEEP_KEY is required}"
: "${MAX_GB:?MAX_GB is required}"

max_bytes=$((MAX_GB * 1000 * 1000 * 1000))
gh cache list --repo "$GITHUB_REPOSITORY" --key "$CACHE_KEY_PREFIX" --limit 100 --json key,sizeInBytes \
  | jq -r --arg keep "$KEEP_KEY" --argjson max "$max_bytes" \
      '.[] | select(.key != $keep or .sizeInBytes > $max) | .key' \
  | while read -r key; do
      echo "delete: $key"
      gh cache delete "$key" --repo "$GITHUB_REPOSITORY" || true
    done
