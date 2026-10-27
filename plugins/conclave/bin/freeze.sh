#!/usr/bin/env bash
# Freeze gate for a set of files (typically contract tests nobody may edit after
# they were accepted). `freeze` records sha256 sums; `verify` checks them.
#
#   freeze.sh freeze <file>...     print `<sha256>  <path>` lines, paths relative to
#                                  the repository root (absolute paths accepted)
#   freeze.sh verify               read those lines on stdin; exit 0 when every file
#                                  is byte-identical, 1 when any changed or is missing
#
# Exit 2 on misuse. Runs from anywhere inside the repository.
set -uo pipefail

usage() { sed -n '2,10p' "$0" >&2; exit 2; }

[[ $# -ge 1 ]] || usage
CMD="$1"; shift

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not inside a git repository" >&2; exit 2; }
cd "$ROOT" || exit 2

case "$CMD" in
  freeze)
    [[ $# -ge 1 ]] || { echo "freeze needs at least one file" >&2; usage; }
    files=()
    for f in "$@"; do
      f="${f#"$ROOT"/}"
      [[ -f "$f" ]] || { echo "no such file: $f" >&2; exit 2; }
      files+=("$f")
    done
    sha256sum -- "${files[@]}"
    ;;
  verify)
    [[ $# -eq 0 ]] || { echo "verify takes no arguments; pass the sums on stdin" >&2; usage; }
    sums=$(cat)
    [[ -n "${sums//[[:space:]]/}" ]] || { echo "no checksums on stdin" >&2; exit 2; }
    if printf '%s\n' "$sums" | sha256sum --check --strict -; then exit 0; else exit 1; fi
    ;;
  *) echo "unknown command: $CMD" >&2; usage ;;
esac
