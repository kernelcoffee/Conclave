#!/usr/bin/env bash
# Scope gate for a change: every file changed since a base ref (committed, staged,
# unstaged or untracked) must lie under one of the allowed prefixes. Prints one
# `out of scope: <file>` line per violation. Exit 0 when the change stays in scope,
# 1 when any file is outside it, 2 on misuse.
#
#   scope-check.sh <base-ref> <prefix-or-glob>...
#
#   A prefix ending in `/` matches everything under that directory; an argument with
#   `*` or `?` is a glob matched against the whole repo-relative path (`**` spans
#   directories); anything else must match the path exactly. Absolute arguments are
#   accepted and compared relative to the repository root.
#
# Runs from anywhere inside the repository; paths are relative to its top level.
set -uo pipefail

usage() { sed -n '2,15p' "$0" >&2; exit 2; }

[[ $# -ge 2 && "$1" != --* ]] || usage
BASE="$1"; shift

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not inside a git repository" >&2; exit 2; }
cd "$ROOT" || exit 2
git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null || { echo "unknown base ref: $BASE" >&2; exit 2; }

PATTERNS=()
for p in "$@"; do
  p="${p#"$ROOT"/}"
  [[ -n "$p" ]] || { echo "empty prefix" >&2; usage; }
  PATTERNS+=("$p")
done

# Glob matching with ** spanning directories, * and ? within one segment.
glob_to_re() {
  local g="$1" re="" i c
  for ((i = 0; i < ${#g}; i++)); do
    c="${g:i:1}"
    case "$c" in
      \*)
        if [[ "${g:i:3}" == "**/" ]]; then re+="(.*/)?"; i=$((i + 2))
        elif [[ "${g:i:2}" == "**" ]]; then re+=".*"; i=$((i + 1))
        else re+="[^/]*"; fi ;;
      \?) re+="[^/]" ;;
      [.+^\$\(\)\|\[\]\{\}\\]) re+="\\$c" ;;
      *) re+="$c" ;;
    esac
  done
  printf '^%s$' "$re"
}

in_scope() {
  local f="$1" p
  for p in "${PATTERNS[@]}"; do
    if [[ "$p" == */ ]]; then
      [[ "$f" == "$p"* ]] && return 0
    elif [[ "$p" == *[\*\?]* ]]; then
      [[ "$f" =~ $(glob_to_re "$p") ]] && return 0
    else
      [[ "$f" == "$p" ]] && return 0
    fi
  done
  return 1
}

changed=$({ git diff --name-only "$BASE"; git ls-files --others --exclude-standard; } | sort -u)
bad=0
while IFS= read -r f; do
  [[ -n "$f" ]] || continue
  if ! in_scope "$f"; then
    echo "out of scope: $f"
    bad=1
  fi
done <<< "$changed"
exit "$bad"
