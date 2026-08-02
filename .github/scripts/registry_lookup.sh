#!/usr/bin/env bash
# Classify registry manifest lookups without treating every failure as absence.

registry_manifest_digest() {
  local ref="$1"
  local max_attempts="${REGISTRY_LOOKUP_MAX_ATTEMPTS:-3}"
  local timeout_seconds="${REGISTRY_LOOKUP_TIMEOUT_SECONDS:-30}"
  local retry_delay="${REGISTRY_LOOKUP_RETRY_DELAY_SECONDS:-1}"
  local attempt status stdout_file stderr_file output error digest

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
      if digest=$(jq -er \
        '.manifest.digest | strings | select(test("^sha256:[0-9a-f]{64}$"))' \
        <<<"${output}"); then
        printf '%s\n' "${digest}"
        return 0
      fi
      echo "Registry returned invalid manifest metadata for ${ref}" >&2
      return 2
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
      return 1
    fi

    printf 'Unclassified registry lookup failure for %s (exit %s): %s\n' \
      "${ref}" "${status}" "${error}" >&2
    return 2
  done
}
