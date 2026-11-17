#!/usr/bin/env bash
# Classify registry manifest lookups without treating every failure as absence.
#
# registry_inspect_json      - retries transient failures and prints the full
#                              `imagetools inspect --format '{{json .}}'`
#                              document on success. Exit codes: 0 success,
#                              1 the ref is definitively absent (404/unknown),
#                              2 any other failure (auth, transient-after-
#                              retries, unclassified).
# registry_manifest_digest   - prints the sha256 manifest digest for a ref;
#                              exit codes as above, plus 2 for invalid metadata.
# registry_preflight_release_images
#                            - checks release images before any tag moves.
#                              Exit codes: 0 clean, 1 conflicts, 2 lookup failure.

registry_inspect_json() {
  local ref="$1"
  local max_attempts="${REGISTRY_LOOKUP_MAX_ATTEMPTS:-3}"
  local timeout_seconds="${REGISTRY_LOOKUP_TIMEOUT_SECONDS:-30}"
  local retry_delay="${REGISTRY_LOOKUP_RETRY_DELAY_SECONDS:-1}"
  local attempt status stdout_file stderr_file output error

  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    stdout_file=$(mktemp)
    stderr_file=$(mktemp)
    status=0
    timeout --kill-after=5 "${timeout_seconds}" \
      docker buildx imagetools inspect "${ref}" --format '{{json .}}' \
      >"${stdout_file}" 2>"${stderr_file}" || status=$?
    output=$(<"${stdout_file}")
    error=$(<"${stderr_file}")
    rm -f "${stdout_file}" "${stderr_file}"

    if [ "${status}" -eq 0 ]; then
      printf '%s\n' "${output}"
      return 0
    fi

    if printf '%s\n' "${error}" | grep -Eiq \
      '401[[:space:]]+Unauthorized|403[[:space:]]+Forbidden|authentication required|authorization failed|failed to authorize|pull access denied|requested access (to the resource )?is denied|(^|[^[:alnum:]_])(UNAUTHORIZED|DENIED|insufficient[_ ]scope)([^[:alnum:]_]|$)'; then
      printf 'Registry authorization failed for %s: %s\n' "${ref}" "${error}" >&2
      return 2
    fi

    if [ "${status}" -eq 124 ] || [ "${status}" -eq 137 ] || [ "${status}" -eq 102 ] \
      || printf '%s\n' "${error}" | grep -Eiq \
        '408[[:space:]]+Request Timeout|429[[:space:]]+Too Many Requests|5[0-9]{2}[[:space:]]+[A-Za-z]|TOOMANYREQUESTS|too many requests|rate[- ]?limit|timeout|timed out|context deadline exceeded|temporary failure in name resolution|no such host|server misbehaving|connection (reset|refused|aborted)|network is unreachable|unexpected EOF|TLS handshake timeout'; then
      if [ "${attempt}" -lt "${max_attempts}" ]; then
        echo "Transient registry lookup failure for ${ref}; retrying (${attempt}/${max_attempts})" >&2
        sleep $((retry_delay * attempt))
        continue
      fi
      printf 'Registry lookup failed after %s attempts for %s: %s\n' \
        "${max_attempts}" "${ref}" "${error}" >&2
      return 2
    fi

    if printf '%s\n' "${error}" | grep -Eiq \
      '404[[:space:]]+Not Found|MANIFEST_UNKNOWN|manifest unknown|NAME_UNKNOWN|name unknown' \
      || [ "${error}" = "ERROR: ${ref}: not found" ]; then
      printf 'Registry image not found: %s (%s)\n' "${ref}" "${error}" >&2
      return 1
    fi

    printf 'Unclassified registry lookup failure for %s (exit %s): %s\n' \
      "${ref}" "${status}" "${error}" >&2
    return 2
  done
}

registry_manifest_digest() {
  local ref="$1" output digest

  output=$(registry_inspect_json "${ref}") || return $?
  if digest=$(jq -er \
    '.manifest.digest | strings | select(test("^sha256:[0-9a-f]{64}$"))' \
    <<<"${output}"); then
    printf '%s\n' "${digest}"
    return 0
  fi
  echo "Registry returned invalid manifest metadata for ${ref}" >&2
  return 2
}

# Release validation and promotion both run this preflight: once against the
# build metadata and again against the sealed plan right before tags move.
# Reads "<source-ref> TAB <release-ref> TAB <digest>" lines on stdin. Every
# source ref must still resolve to its digest, and no release tag may already
# point elsewhere. Reports every conflict before failing.
registry_preflight_release_images() {
  local conflicts=0 source_ref release_ref digest observed lookup_status

  while IFS=$'\t' read -r source_ref release_ref digest; do
    lookup_status=0
    observed=$(registry_manifest_digest "${source_ref}") || lookup_status=$?
    if [ "${lookup_status}" -eq 1 ]; then
      echo "Source image not found: ${source_ref}" >&2
      conflicts=1
    elif [ "${lookup_status}" -ne 0 ]; then
      return "${lookup_status}"
    elif [ "${observed}" != "${digest}" ]; then
      echo "Source digest mismatch for ${source_ref}: ${observed} != ${digest}" >&2
      conflicts=1
    fi

    lookup_status=0
    observed=$(registry_manifest_digest "${release_ref}") || lookup_status=$?
    if [ "${lookup_status}" -eq 0 ] && [ "${observed}" != "${digest}" ]; then
      echo "Release tag conflict: ${release_ref} points to ${observed}, expected ${digest}" >&2
      conflicts=1
    elif [ "${lookup_status}" -ne 0 ] && [ "${lookup_status}" -ne 1 ]; then
      return "${lookup_status}"
    fi
  done
  [ "${conflicts}" -eq 0 ]
}
