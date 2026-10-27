---
name: init
description: Create the Conclave project profile (.claude/conclave.json) by scanning the repo for components, stacks, check commands, docs, CI and gates. Run once per project before /conclave, and again when the build or test setup changes.
argument-hint: "[--force]"
user-invocable: true
---
Write `.claude/conclave.json` for the current project. The profile is the only per-project artifact the Conclave team needs; everything the agents used to hard-code (paths, commands, stacks, stakes) lives here.

Arguments: `$ARGUMENTS`. If the file already exists and `--force` is not given, do not rewrite it. Instead:

1. Validate it against `${CLAUDE_PLUGIN_ROOT}/schemas/conclave.schema.json` (same command as in step 2) and report any error with the path of the offending key.
2. Compare it with `${CLAUDE_PLUGIN_ROOT}/templates/conclave.json` and list the keys the template has that the profile lacks, one line each with what it does (from the schema `description`). These are features added by a newer Conclave; they are optional and default to off.
3. Check that every command in `checks`, `build` and `e2e` still exists (the script or binary is there) and that every `paths` entry still exists; report what moved.
4. Stop. The user edits the profile, or runs `/conclave:init --force` to regenerate it.

## 1. Scan

Read before you guess; name only paths and commands you verified exist.

- **Components and stacks.** Look for build files and map them to stack packs: `pyproject.toml`, `setup.py`, `requirements*.txt` → `python` (plus `fastapi` when FastAPI is a dependency); `package.json` → `typescript` (plus `react` when React is a dependency); `CMakeLists.txt`, `*.pro`, `*.qbs` or any `.cpp`/`.h` sources → `cpp` (plus `qt6` when the build references `Qt6`/`find_package(Qt6`, or `qt5` when it references `Qt5`/`QT +=` in a `.pro`; never both); `Cargo.toml` → `rust`; `*.toc` with `.lua` files → `lua`; shell-only repos → `shell`; anything else → `generic`. A build file in a subdirectory (`backend/`, `frontend/`, `src/`) marks that directory as a component's path. One build file at the root means one component whose path is the source directory.
- **Checks.** From `pyproject.toml` (ruff, mypy, pytest config), `package.json` scripts (`lint`, `test`, `test:run`, `build`, `test:e2e`), `CMakeLists.txt` (`ctest`), `Cargo.toml` (`cargo clippy`, `cargo test`), `Makefile` targets, and CLAUDE.md's Commands section. Prefer the exact commands CLAUDE.md documents, including venv paths such as `backend/.venv/bin/...`. Fast checks go in `checks` (lint, typecheck, unit tests); slow ones in `build` and `e2e`.
- **Tests.** Test directories and globs per component (`tests/`, `backend/tests/`, `src/**/*.test.ts`, `e2e/`).
- **Coverage.** `pytest-cov`, `diff-cover`, vitest `coverage` reporters, `gcov`/`lcov`, `cargo-llvm-cov`. Fill `coverage.command` and `coverage.report` only when the tooling is installed or declared; otherwise omit `coverage` and leave `gates.coverage_changed_lines` out.
- **Base ref.** `git symbolic-ref refs/remotes/origin/HEAD` gives `origin/<branch>`; fall back to `git branch --show-current` with the `origin/` prefix, else `origin/main`.
- **Docs.** `docs/`, `README.md`, `CONTRIBUTING.md`, and any roadmap or todo file CLAUDE.md names. `CLAUDE.md` goes under `docs.never` unless CLAUDE.md itself asks to be kept current.
- **DevOps.** `.github/workflows/*.yml`, `Dockerfile`, `docker-compose*.yml`, `scripts/`, and whether CLAUDE.md says `podman` or `docker`. Version files that must be bumped together (`pyproject.toml`, `package.json`, `Cargo.toml`, `CMakeLists.txt` project version) go in `devops.release`.
- **Contracts.** Two components where one calls the other over HTTP, WebSocket, IPC or a shared schema get a `contracts` pair.
- **Conventions and pitfalls.** Take project rules from CLAUDE.md's Conventions or Rules section into the matching component's `conventions`. Leave `pitfalls` with a TODO line unless CLAUDE.md states gotchas explicitly.
- **Risky paths.** Migrations directories, auth modules, anything that deletes files or touches secrets go in `tier_overrides.risky_paths`.

## 2. Compose

Start from `${CLAUDE_PLUGIN_ROOT}/templates/conclave.json` and keep only what applies. Validate against `${CLAUDE_PLUGIN_ROOT}/schemas/conclave.schema.json`:

```bash
python3 -c "import json,sys; from jsonschema import validate; validate(json.load(open('.claude/conclave.json')), json.load(open(sys.argv[1])))" "${CLAUDE_PLUGIN_ROOT}/schemas/conclave.schema.json"
```

If `jsonschema` is not installed, check by hand: `name`, `base`, `components` present; every component has `name`, `paths`, `stacks`, `checks`; every stack is in the schema's enum; no keys outside the schema.

Values you cannot infer get a visible marker inside the value so the user fills them in: `"stakes": "TODO: what a severity-high defect does to a real user"`, `"security": {"threat_model": "TODO: who can reach the app and what must never leak"}`, `"pitfalls": ["TODO: what this codebase gets wrong under pressure"]`.

## 3. Write and report

Write `.claude/conclave.json` (create `.claude/` if needed). Then print, in this order:

1. The profile you wrote, as a fenced JSON block.
2. The TODO fields the user should fill, one line each.
3. Commands you listed but could not run to confirm (missing venv, missing node_modules), one line each.
4. If `.claude/agents/` or `.claude/workflows/dev-team.js` exist in this project: say that the Conclave plugin replaces that local team, list those files as candidates for deletion, and note that the "Agent team" section of CLAUDE.md should point at `/conclave` instead. Do not delete anything.

Do not ask questions; the user edits the file afterwards.
