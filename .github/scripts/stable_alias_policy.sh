#!/usr/bin/env bash
# Resolve whether VERSION is currently the highest stable Open AD Kit tag.

current_latest_alias_policy() {
  local stable_re='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
  local existing_tag_refs existing_stable_tags highest_stable

  : "${VERSION:?VERSION is required}"
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

  existing_tag_refs=$(
    gh api --paginate "repos/${GITHUB_REPOSITORY}/git/matching-refs/tags/v" \
      --jq '.[].ref | sub("^refs/tags/"; "")'
  ) || return 2
  existing_stable_tags=$(printf '%s\n' "${existing_tag_refs}" | grep -E "${stable_re}" || true)
  highest_stable=$(
    {
      printf '%s\n' "${VERSION}"
      printf '%s\n' "${existing_stable_tags}"
    } | grep -E "${stable_re}" | sort -V | tail -n 1
  )

  if [ "${highest_stable}" = "${VERSION}" ]; then
    printf '%s\n' true
  else
    printf '%s\n' false
  fi
}
