# Conclave

Conclave is a Claude Code plugin that ships a full software team as subagents: product
manager, architect, developer, challenger, reviewers, refuter, test engineer, QA, docs
writer, devops and UX. A lead sizes each task into a tier before anything runs, prints the
agent count and model mix it is about to spend, then does small work itself and dispatches
the team only when parallel builds or black-box verification earn it.

The team is project-agnostic. Everything specific to a project (components, paths, check
commands, stacks, stakes, threat model, docs, gates) lives in one profile file,
`.claude/conclave.json`, that `/conclave:init` generates. Stack knowledge (Python,
FastAPI, TypeScript, React, C++, Qt 6, Qt 5, Rust, Lua, shell) ships as skills the roles load on
demand, so adding a stack is one file.

## Install

From a local checkout:

```bash
claude plugin marketplace add ~/Work/personal/Conclave
claude plugin install conclave@conclave
```

From git:

```
/plugin marketplace add <owner>/Conclave
/plugin install conclave@conclave
```

Development loop, from a project directory:

```bash
claude --plugin-dir ~/Work/personal/Conclave/plugins/conclave
```

then `/reload-plugins` after editing an agent, skill or workflow. Validate with
`claude plugin validate plugins/conclave`.

## Quick start

1. In a project: `/conclave:init`. Review the generated `.claude/conclave.json`, fill the
   `TODO` values (stakes, threat model, pitfalls), fix any command it could not verify.
2. `/conclave <task>`. The lead prints a triage line such as
   `Tier T2 · backend · ~9 agents · opus×7 sonnet×2 · build → challenge×1 → review → verify → tests → qa`
   and then executes it. Add `--dry-run` to see the plan without spending anything,
   `--tier N` to force a tier.
3. When the run reports `ready_to_commit`, the lead proposes a commit message, split into
   the build-safe slices the dev declared in its commit plan. Nothing is committed until
   you approve.

## Tiers

| Tier | When | What runs | Agents |
|---|---|---|---|
| T0 | No behaviour change: typo, comment, wording, config value, question | Lead inline | 0 |
| T1 | One component, at most 3 files, existing patterns, no new public surface, clear spec | Lead implements, one correctness reviewer, lead fixes | 1 |
| T2 | One component, new behaviour or more files, tests needed, spec clear | `dev-team`: build, challenge (1 round), review (correctness, security, stack), verify, tests, QA | about 8 to 12 |
| T3 | Two or more components or a contract, a risky path, an unclear spec, or `--tier 3` | Full pipeline: pm, architect, consult, build in parallel, cross-check, challenge (2 rounds), all lenses, verify (3 votes on high), fix, tests, docs, QA | 20 or more |

A path listed in `tier_overrides.risky_paths` raises any task to at least T2;
`tier_overrides.min_tier` sets a floor.

## T3 options

Off by default; each one is a flag on `/conclave` or a profile setting.

- `--contract` (`exec.contract`): the test engineer writes the contract tests from the
  architect's failure matrix before any code exists, each with its declared expected
  failure; the test-auditor confirms every test fails exactly as declared, the verifier
  freezes them by checksum, and the devs may not edit them. Costs the auditor pass and a
  verifier call; set `tier_overrides.contract_by_default` to make it the T3 default.
- `--duel` (`exec.design = "duel"`): two devs with the specialities the architect names
  propose a design, critique each other, and the architect judges or merges. About five
  extra agents; `tier_overrides.design_duel_by_default` makes it the T3 default.
- `gates.mutation_probes` (profile): after the build passes, the test-auditor sabotages
  the implementation once per contract test, requires the test to fail, restores the file
  and proves it by checksum. Catches tests that pass for the wrong reason; one rebuild per
  probe, so costly on compiled stacks.

## Roles

| Agent | What it does | Default model |
|---|---|---|
| `lead` | Triage, tier, model choice, inline work at T0/T1, launches workflows, proposes the commit | session |
| `pm` | Spec, goals, acceptance criteria, components touched, decisions only the user can make | session |
| `architect` | Per-component briefs, contracts, expected-failure matrix, ad-hoc specialists | session |
| `dev` | Builds one component from its brief, writes tests, runs the checks | opus |
| `challenger` | Same-stack adversary: re-derives the change, writes failing proof tests, escalates weak rebuttals | opus |
| `reviewer-correctness` | Real bugs with a concrete failure scenario | opus |
| `reviewer-security` | Threat-model driven review; also the `/conclave:audit` sweeper | opus |
| `reviewer-conventions` | Project rules from the profile and CLAUDE.md, maintainability, scope | sonnet |
| `reviewer-stack` | Language and framework lens; loads the stack pack named in its task | opus |
| `ux` | User-facing review of `ui` components; consultant before the build | opus |
| `refuter` | Tries to refute each finding; only what survives reaches the devs | opus |
| `test-engineer` | Black-box tests from the failure matrix, written before reading the implementation | opus |
| `qa` | Checks, build, e2e, coverage gate, shortcut audit, flake runs | sonnet |
| `docs-writer` | Keeps the docs the profile names in step with the change | sonnet |
| `devops` | CI, containers, packaging, version bumps, release | opus |
| `verifier` | Runs gate commands (scope, freeze, checks) and reports exit codes and output verbatim; never fixes | sonnet |
| `test-auditor` | Audits contract tests fail exactly as declared and are not tautologies; runs mutation probes | opus |

Override by role or group (`planners`, `workers`, `reviewers`, `mechanical`, `refuter`) in
the profile's `models` block. No subagent ever commits.

## Commands

| Command | Does |
|---|---|
| `/conclave <task> [--tier N] [--rounds N] [--dry-run]` | Triage and run the task |
| `/conclave:init [--force]` | Generate `.claude/conclave.json` |
| `/conclave:plan <task>` | pm and architect only; spec, decisions, briefs, no code |
| `/conclave:review [base-ref] [--lenses a,b,c]` | Review and refute the working-tree diff; changes nothing |
| `/conclave:release <version>` | devops bumps versions, drafts the changelog, checks CI, proposes commit and tag |
| `/conclave:audit [path]` | Whole-repo security sweep, one reviewer per component, refuters on high findings |

Workflows (`/conclave:dev-team`, `/conclave:review`, `/conclave:plan`) can also be
launched directly with `args: { profile, exec }`; see `docs/design.md` for `exec`.

## The profile

`.claude/conclave.json` describes the project: `components` (each with `paths`, `tests`,
`stacks`, `checks`, optional `build`, `e2e`, `coverage`, `setup`, `pitfalls`,
`conventions`, `ui`), `contracts` between components, `stakes` (what severity `high`
means here), `security.threat_model`, `docs`, `devops`, `gates`, `git`, `models` and
`tier_overrides`. Start from `plugins/conclave/templates/conclave.json`; the schema is
`plugins/conclave/schemas/conclave.schema.json`. Findings are routed to the dev that owns
the path, the docs writer, or devops by matching these entries. The same entries drive
`bin/scope-check.sh` and `bin/freeze.sh`, which the verifier runs so that path ownership
and frozen contract tests are enforced mechanically, not by prose.

## Stack packs

| Pack | Covers |
|---|---|
| `stack-python` | Typing, asyncio, exceptions, resources, pytest, ruff, mypy, pytest-cov |
| `stack-fastapi` | Routers, dependencies, sessions and transactions, schemas, WebSockets, schedulers |
| `stack-typescript` | Strictness, narrowing, async, API type fidelity, vitest, tsc, eslint |
| `stack-react` | Hooks and effects, queries, state, rendering, forms, theme and layout, Playwright |
| `stack-cpp` | Standard modern C++: const and initialisation discipline, ownership and RAII, strong types, warnings as errors, sanitizers, clang-tidy, ctest |
| `stack-qt6` | Qt 6 on its own terms: object tree, signals and slots, threads and event loops, QML/C++ boundary, Qt SQL, Qt Test, clazy, qmllint |
| `stack-qt5` | Legacy Qt 5.15: what still applies, what is deprecated or missing, forward compatibility, qmake |
| `stack-rust` | Ownership, error handling, async, unsafe, cargo clippy, cargo test, llvm-cov |
| `stack-lua` | Addon and script idioms, globals, event handlers, busted |
| `stack-shell` | bash strict mode, quoting, portability, shellcheck, bats |
| `stack-generic` | Fallback checklist for stacks without a pack |

Adding a stack:

1. Add `plugins/conclave/skills/stack-<name>/SKILL.md` with the sections Idioms, Review
   checklist, Testing, Tooling, Pitfalls.
2. Add `<name>` to the `stacks` enum in `plugins/conclave/schemas/conclave.schema.json`.
3. Add a row to the table above.

## Migrating a project with the legacy team

Projects that carry their own `.claude/agents/*.md` and `.claude/workflows/dev-team.js`
get the same pipeline from the plugin. Run
`/conclave:init`, compare the generated profile with the project's CLAUDE.md commands,
move project-specific lines from the old agent files into the profile's `pitfalls`,
`conventions`, `stakes` and `security.threat_model`, then delete the local agents and
workflow and point the "Agent team" section of CLAUDE.md at `/conclave`. The gate scripts
`scripts/check-coverage.sh` and `scripts/shortcut-audit.sh` are replaced by the plugin's
`bin/diff-coverage.sh` and `bin/shortcut-audit.sh`, driven by the profile's `coverage` and
`gates` entries, and `bin/scope-check.sh` and `bin/freeze.sh` take over any local scope or
checksum gates.

## Design

`docs/design.md` is the contract between the pieces: principles, tiers, model policy, the
`exec` object, what every subagent prompt contains, return shapes, file ownership, agent
file conventions and the stack pack format.
