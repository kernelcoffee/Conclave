---
name: stack-shell
description: Knowledge pack for bash and POSIX shell scripts (build, CI, release, gate scripts): idioms, review checklist, testing, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead.
user-invocable: false
---
# Shell stack pack

Applies to bash scripts under `scripts/`, `bin/` or CI steps. Anything longer than about
a hundred lines or needing data structures should be Python instead; say so in the report.

## Idioms

- `#!/usr/bin/env bash` and strict mode `set -euo pipefail` (drop `-e` only in a script
  whose whole purpose is to collect failures, and say so in a comment); `IFS=$'\n\t'`
  when splitting on whitespace would be wrong.
- Quote every expansion: `"$var"`, `"${arr[@]}"`, `"$(cmd)"`; arrays for lists of paths;
  `[[ ]]` for tests; `$(...)` not backticks; `printf` not `echo` for anything with
  escapes or a leading dash.
- Resolve the repo root with `git rev-parse --show-toplevel` instead of `cd "$(dirname "$0")/.."`
  when the script must run from anywhere; use `mktemp -d` with a `trap ... EXIT` cleanup.
- A usage function, argument parsing with `while [[ $# -gt 0 ]]; do case "$1" in ...`,
  exit codes documented (0 ok, 1 findings, 2 misuse or missing tool).
- Functions for repeated steps; `local` variables; `readonly` for constants.
- Output: progress to stderr, data to stdout, so the script composes in a pipe.
- Portability: avoid GNU-only flags when macOS matters, or state the requirement at the top.

## Review checklist

- Unquoted expansions, `for f in $(ls ...)`, word splitting on paths with spaces.
- Missing `set -euo pipefail`; a pipeline whose failure is masked (`cmd | tail` without
  `pipefail`); `cd` without `||exit`.
- `rm -rf` on a variable that can be empty (`rm -rf "$dir/"` with `dir` unset deletes `/`);
  guard with `${dir:?}`.
- A temp file without cleanup; a lock file never released.
- Parsing output of `ls`, `find` without `-print0`, `grep` without `-F` on literal input.
- Secrets echoed or passed on a command line visible in `ps`; `set -x` left on.
- Hardcoded absolute paths; assumptions about the current directory.
- `eval` on user input; `curl | sh` patterns.
- Exit codes not propagated from inner commands; `exit 0` at the end masking failures.

## Testing

- `bash -n script.sh` for syntax; `shellcheck script.sh` clean (no `# shellcheck disable`
  added to silence a real issue).
- bats (`@test "..." { run ...; [ "$status" -eq 0 ]; [[ "$output" == *expected* ]] }`) for
  behaviour; fixtures in a temp dir; the script under test invoked by path, never sourced
  unless it is a library.
- Run the script against a real small repo or fixture directory in CI; assert on exit code
  and on files produced.

## Tooling

- `shellcheck -x` (follows `source`), `shfmt -d -i 2` for formatting if the project uses it.
- bats-core installed through npm or the package manager; `bats tests/`.
- In CI, scripts run with the same shell and flags as locally; pin `bash` on macOS runners
  when features from bash 4+ are used.

## Pitfalls

- `set -e` not firing inside `if cmd; then`, `cmd && ...`, or a function called in a
  condition; check return codes explicitly where it matters.
- `read` without `-r` mangling backslashes; `read` in a `while` loop consuming stdin
  from the wrong source.
- `grep` returning 1 on no match and aborting the script under `set -e`; append `|| true`
  deliberately and comment it.
- Locale-dependent sorting and `[a-z]` ranges; export `LC_ALL=C` for deterministic output.
- Getting the script directory with `$0` when the script is sourced or symlinked.
