#!/usr/bin/env bash
# Coverage gate on changed lines: judges a Cobertura XML or lcov report with diff-cover
# against a base ref. Exit 0 when the added or modified lines are covered at least
# <fail-under> percent, 1 when not, 2 when diff-cover is missing or the call is wrong.
#
#   diff-coverage.sh <report> <base-ref> <fail-under> [--src-root DIR] [--include GLOB...]
#
#   <report>      Cobertura XML (pytest-cov, gcovr, cargo llvm-cov) or lcov .info file,
#                 relative to the repo root
#   --src-root    directory the report's paths are relative to (ignored by diff-cover for
#                 lcov input; prefix the paths in the report instead)
#   --include     one or more globs limiting which files are judged; all patterns go in a
#                 single --include, since a repeated flag keeps only the last one
#
# Runs from anywhere inside the repository.
set -uo pipefail

usage() { sed -n '2,15p' "$0" >&2; exit 2; }

[[ $# -ge 3 ]] || usage
REPORT="$1"; BASE="$2"; MIN="$3"; shift 3
[[ "$MIN" =~ ^[0-9]+$ && "$MIN" -le 100 ]] || { echo "fail-under must be an integer 0-100, got: $MIN" >&2; usage; }
SRC_ROOT=""
INCLUDE=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --src-root) [[ $# -ge 2 ]] || usage; SRC_ROOT="$2"; shift ;;
    --include) shift; while [[ $# -gt 0 && "$1" != --* ]]; do INCLUDE+=("$1"); shift; done; continue ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
  shift
done

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not inside a git repository" >&2; exit 2; }
cd "$ROOT" || exit 2
[[ -f "$REPORT" ]] || { echo "coverage report not found: $REPORT (run the component's coverage command first)" >&2; exit 2; }
git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null || { echo "unknown base ref: $BASE" >&2; exit 2; }

# Locate diff-cover: PATH, then common virtualenv layouts one level deep, then module
# or pipx invocation.
find_diff_cover() {
  local c
  if c=$(command -v diff-cover 2>/dev/null); then echo "$c"; return 0; fi
  for c in ./backend/.venv/bin/diff-cover ./.venv/bin/diff-cover ./venv/bin/diff-cover \
           ./*/.venv/bin/diff-cover ./*/venv/bin/diff-cover; do
    [[ -x "$c" ]] && { echo "$c"; return 0; }
  done
  if python3 -c 'import diff_cover' 2>/dev/null; then echo "python3 -m diff_cover.diff_cover_tool"; return 0; fi
  if command -v pipx >/dev/null 2>&1; then echo "pipx run diff-cover"; return 0; fi
  return 1
}

if ! DIFF_COVER=$(find_diff_cover); then
  cat >&2 <<'EOF'
diff-cover is not installed. Install it in the project's virtualenv or globally:
  .venv/bin/pip install diff-cover        # inside the component's venv
  pipx install diff-cover                 # or user-wide
  pip install --user diff-cover
EOF
  exit 2
fi

args=("$REPORT" --compare-branch="$BASE" --fail-under="$MIN")
[[ -n "$SRC_ROOT" ]] && args+=(--src-root "$SRC_ROOT")
[[ ${#INCLUDE[@]} -gt 0 ]] && args+=(--include "${INCLUDE[@]}")

echo "== diff-cover $REPORT (vs $BASE, fail-under $MIN%)" >&2
# shellcheck disable=SC2086  # DIFF_COVER may be a multi-word command (python3 -m ..., pipx run ...)
$DIFF_COVER "${args[@]}"
exit $?
