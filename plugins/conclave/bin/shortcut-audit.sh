#!/usr/bin/env bash
# Shortcut audit for a change: lists suppressions, skipped or focused tests, swallowed
# errors, debt markers, sleeps and weakened assertions that the change introduced
# relative to a base ref, the test assertions it removed, and whether the number of
# tests dropped. Exit 1 when anything was found; the caller judges whether a hit is
# justified. Exit 2 on misuse.
#
#   shortcut-audit.sh <base-ref> --scope <path>... --tests <path>...
#
#   --scope   code directories audited for added-line markers (relative to the repo root)
#   --tests   directories or files where removed assertions and test counts are measured
#
# Runs from anywhere inside the repository; paths are relative to its top level.
set -uo pipefail

usage() { sed -n '2,13p' "$0" >&2; exit 2; }

[[ $# -ge 1 && "$1" != --* ]] || usage
BASE="$1"; shift
SCOPE=()
TESTS=()
mode=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope) mode=scope ;;
    --tests) mode=tests ;;
    --*) echo "unknown flag: $1" >&2; usage ;;
    *)
      case "$mode" in
        scope) SCOPE+=("$1") ;;
        tests) TESTS+=("$1") ;;
        *) echo "path given before --scope/--tests: $1" >&2; usage ;;
      esac ;;
  esac
  shift
done
[[ ${#SCOPE[@]} -gt 0 ]] || { echo "at least one --scope path is required" >&2; usage; }
[[ ${#TESTS[@]} -gt 0 ]] || TESTS=("${SCOPE[@]}")

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not inside a git repository" >&2; exit 2; }
cd "$ROOT" || exit 2
git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null || { echo "unknown base ref: $BASE" >&2; exit 2; }

found=0
SELF_NAME=$(basename "$0")
EXCLUDE_RE='(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|poetry\.lock|uv\.lock|Pipfile\.lock|composer\.lock)$|\.(svg|png|jpe?g|gif|ico|webp|zip|jar|gz|tgz|bz2|xz|7z|pdf|woff2?|ttf|otf|eot|mp[34]|wav|ogg|bin|so|dll|dylib|a|o|pyc|qm|ts\.gz|qrc)$'

# Added lines: committed changes since the merge base plus the working tree, then
# untracked files in full. Only code and tests are audited; prose legitimately names
# these markers, so keep docs out of --scope.
added() {
  git diff "$BASE" --unified=0 -- "${SCOPE[@]}" \
    | grep -aE '^\+[^+]' | sed 's/^+//'
  git ls-files --others --exclude-standard -- "${SCOPE[@]}" \
    | grep -vE "$EXCLUDE_RE" | grep -v "/$SELF_NAME\$" \
    | while read -r f; do grep -aH '' "$f"; done
}

PATTERN='noqa|type: ?ignore|as any|@ts-ignore|@ts-expect-error|eslint-disable|pytest\.mark\.skip|pytest\.mark\.xfail|\.skip\(|\.only\(|\bxit\(|\bxtest\(|\bxdescribe\(|except Exception:|except:$|except BaseException:|suppress\(Exception|catch *\{ *\}|catch *\([a-zA-Z_]*\) *\{ *\}|\bTODO\b|\bFIXME\b|\bHACK\b|\bXXX\b|time\.sleep\(|waitForTimeout\(|QTest::qWait\(|std::this_thread::sleep_for\(|thread::sleep\(|assert True\b|status_code in \(|# pragma: no cover|#\[allow\(|#\[ignore|allow\(clippy|clang-tidy|NOLINT|cppcheck-suppress|luacheck: ?(ignore|no)|shellcheck disable|QSKIP\(|GTEST_SKIP\(|SKIP\(|@pytest\.mark\.flaky|retries ?[:=]'

echo "== shortcut markers in added lines (vs $BASE)"
hits=$(added | grep -nE "$PATTERN" || true)
if [[ -n "$hits" ]]; then echo "$hits"; found=1; else echo "(none)"; fi

echo
echo "== assertions removed (vs $BASE)"
removed=$(git diff "$BASE" --unified=0 -- "${TESTS[@]}" | grep -aE '^-[^-]' \
  | grep -E '^-[[:space:]]*(assert |assert\(|assert_|expect\(|QCOMPARE\(|QVERIFY\(|QTRY_|EXPECT_|ASSERT_|REQUIRE\(|CHECK\(|assert\.|assert!|assert_eq!|assert_ne!|\[\[? )' || true)
if [[ -n "$removed" ]]; then echo "$removed"; found=1; else echo "(none)"; fi

echo
echo "== test counts (base -> now)"
count_tests() {
  # Counts test definitions across the languages Conclave supports. Arguments are
  # directories or files; missing ones count as zero.
  local n=0 c
  for p in "$@"; do
    [[ -e "$p" ]] || continue
    c=$(grep -rhoE \
      '^\s*(async )?def test_|^\s*(it|test)\(|^\s*(it|test)\.each\(|^\s*TEST(_F|_P)?\(|^\s*TEST_CASE\(|^\s*SCENARIO\(|^\s*(private )?(Q_SLOT )?void test[A-Za-z0-9_]*\(|#\[(tokio::)?test|^\s*@test |^\s*it\(' \
      --include='*.py' --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx' \
      --include='*.cpp' --include='*.cc' --include='*.cxx' --include='*.h' --include='*.hpp' \
      --include='*.rs' --include='*.lua' --include='*.bats' --include='*.sh' \
      "$p" 2>/dev/null | wc -l)
    n=$((n + c))
  done
  echo "$n"
}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git archive "$BASE" -- "${TESTS[@]}" 2>/dev/null | tar -x -C "$tmp" 2>/dev/null
base_paths=()
for p in "${TESTS[@]}"; do base_paths+=("$tmp/$p"); done
before=$(count_tests "${base_paths[@]}")
now=$(count_tests "${TESTS[@]}")
echo "tests: $before -> $now"
if [[ "$now" -lt "$before" ]]; then echo "test count decreased"; found=1; fi
exit $found
