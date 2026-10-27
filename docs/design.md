# Conclave design

Conclave is a Claude Code plugin that ships a full software team as subagents, plus a lead
that decides how much of that team a task deserves. This file is the contract between the
pieces; agent files, skills and workflow scripts all follow it.

## Principles

1. **One main loop holds the context.** The lead (the session itself) triages, plans, and
   does small work directly. Subagents are spawned only for parallel builds, black-box
   verification, and work that would bloat the main context. Every handoff loses detail,
   so there are as few as the tier allows.
2. **Tier before tokens.** The lead prints the tier, the agent count and the model mix
   before anything is dispatched. The workflow script never decides its own shape; it
   executes the `exec` object the lead hands it.
3. **Generic roles, project profile.** Agent bodies contain no project names, paths or
   commands. Everything project-specific lives in `.claude/conclave.json` and in stack
   packs (`skills/stack-*`).
4. **Nobody commits but the user.** Subagents never run `git commit`. The lead proposes a
   commit message and waits for approval.

## Tiers

| Tier | When | Runs |
|---|---|---|
| T0 | no behaviour change: typo, comment, wording, config value, question | lead inline |
| T1 | one component, at most 3 files, existing patterns, no new public surface, clear spec | lead implements inline, one `reviewer-correctness` pass, lead fixes |
| T2 | one component, new behaviour or public surface or more files, tests needed, spec clear | `dev-team` workflow: build, challenge (1 round), review (core lenses + stack), verify (1 vote), tests, qa |
| T3 | two or more components or a contract pair, a risky path, an unclear spec, or the user asks | `dev-team` workflow, full: pm, architect, consult, build, cross-check, challenge (2 rounds), all lenses + ux, verify (3 votes on high), fix, tests, docs, qa |

Bumps: `profile.tier_overrides.min_tier`; any touched path in
`profile.tier_overrides.risky_paths` raises to at least T2; `--tier N` from the user wins.

T3 options (off by default; the lead turns them on when earned, the user with a flag, or
the profile with `tier_overrides.contract_by_default` / `design_duel_by_default`):

| Option | Mechanism | Cost |
|---|---|---|
| `exec.contract` | Test-first: the test engineer writes failing tests with a declared expected failure each; the test auditor confirms every one fails exactly as declared and is not a tautology; the verifier freezes them with `bin/freeze.sh`; devs may not edit them and the verifier checks after every write phase | about 3 agents |
| `exec.design: "duel"` | Two devs with specialities named by the architect each design, then critique the other; the architect judges disagreements or declares them undecidable (a human decision) | 4 or 5 agents |
| `profile.gates.mutation_probes` | After review is clean, the test auditor sabotages the implementation once per test and requires the test to fail, restoring the tree and proving it by checksum; the test engineer repairs tests that survived, once | 1 to 3 agents, plus a rebuild per probe on compiled stacks |

Always on at T2 and above: the `verifier` (sonnet, low effort) runs `bin/scope-check.sh`
after Build, after each Fix round and after test-engineer bug fixes. Out-of-scope files go
back to their owner once; QA runs the same gate at the end. The docs phase ends with a
second `docs-writer` call in audit mode and a fix pass when it reports corrections.

## Model and effort policy

| Group | Roles | Default model | Effort |
|---|---|---|---|
| planners | lead, pm, architect | inherit (session model) | high |
| refuter | refuter | opus (session model for `high` at T3) | high |
| workers | dev, challenger, test-engineer, devops | opus | high |
| reviewers | reviewer-correctness, reviewer-security, reviewer-stack, ux, test-auditor | opus | high |
| mechanical | reviewer-conventions, docs-writer, qa, verifier, profile reader | sonnet | medium (qa, verifier and profile reader: low) |

Override order: `exec.models[role]` > `exec.models[group]` > `profile.models[role]` >
`profile.models[group]` > defaults. `inherit` means no model option is passed.

## Interfaces

### Profile (`.claude/conclave.json`)

See `plugins/conclave/schemas/conclave.schema.json`. Key fields the scripts rely on:
`name`, `base`, `components[]` (`name`, `paths`, `tests`, `stacks`, `ui`, `checks`,
`build`, `e2e`, `coverage`, `setup`, `pitfalls`, `conventions`), `contracts`, `stakes`,
`security`, `docs`, `devops`, `gates`, `git`, `models`, `tier_overrides`.

### Execution plan (`exec`, built by the lead, consumed by `workflows/dev-team.js`)

```js
{
  tier: 2,                       // 2 or 3; the lead handles 0 and 1 itself
  task: "the user's request, verbatim plus any clarifications",
  brief: "",                     // T2: the lead's own brief (pm and architect are skipped); T3: empty
  components: ["backend"],       // component names the task touches (the architect may extend at T3)
  rounds: 1,                     // challenge and review rounds
  lenses: ["correctness", "security", "stack"],   // plus "conventions", "ux" when earned
  refute_votes_high: 1,          // 3 at T3
  skip: [],                      // any of pm, architect, consult, crosscheck, challenge, tests, docs, qa
  models: {}, effort: {},        // per-role or per-group overrides
  base: "origin/main",
  contract: false,               // T3 option: test-first contract tests, audited and frozen
  design: "",                    // T3 option: "duel"
  dev_specialities: [],          // optional override of the architect's duel specialities
  decisions: "", proceed: false, // resume after a needs-human stop
  briefs_from_files: false,      // force agents to read their brief from the plugin agents dir
  plugin_root: "/abs/path/plugins/conclave"
}
```

Workflow args: `{ profile, exec }`. When `profile` is missing the script spends one
low-effort agent to read `.claude/conclave.json`.

### What a workflow returns

Every workflow returns a `status`:

- `needs-human`: stopped in `phase` with `decision_request: { question, context }`. Any
  phase can stop: pm or architect decisions, a frozen test modified after the freeze, a
  tree the test auditor could not prove restored, an undecidable design duel, exhausted
  review rounds with open findings, a role that returned nothing. The lead handles every
  one the same way: ask the user, relaunch with `exec.decisions`, `exec.proceed: true`
  and `skip` narrowed to the phases already passed.
- `accepted`: review clean and QA green (`ready_to_commit: true`), with `commit_plan`:
  ordered build-safe slices (`title`, `files`, `rationale`) that the lead proposes as
  separate commits: frozen contract tests first, each dev's slices, test additions, docs.
- `not-ready`: finished but a gate is red; `qa` says which.

### What every subagent prompt contains

The script builds a context block and prepends it to each role's task:

```
Project: <name>. <summary>
Base ref: <base>
Stakes (severity high means): <stakes>
Threat model: <security.threat_model>

Task:
<task>

Component(s) you work on:
<JSON of the relevant component entries: paths, tests, stacks, checks, pitfalls, conventions>

Stack packs: load each with the Skill tool before you start: conclave:stack-python, ...

Contract(s):
<text or "(none)">

Expected failures:
- behaviour | input or state | expected outcome
```

Agents may also read `.claude/conclave.json` themselves. CLAUDE.md is injected by Claude
Code; prompts never paste it.

### Return shapes

Enforced by JSON schema in the script: `SPEC` (pm), `PLAN` (architect, plus
`dev_specialities`), `DESIGN`, `CRITIQUE`, `JUDGEMENT_DESIGN` (duel), `DEV` (plus
`commit_plan`), `CROSSCHECK`, `CHALLENGE`, `FINDINGS`, `VERDICT`, `RECHECK`, `TESTS`
(plus `test_files`, `contract_tests`, `could_not_reproduce`), `RED_AUDIT` and `PROBES`
(test-auditor), `VERIFY` (verifier: `runs` of `{command, exit_code, output_tail}` and
`all_passed`), `DOCS`, `DOC_AUDIT`, `QA`. Every finding carries `file`, `line`,
`severity` (`high`/`medium`/`low`), `summary`, `failure_scenario`. Severity `high` is
defined by `profile.stakes`.

### Mechanical gates (`bin/`)

Generic scripts any project can run; QA and the verifier call them with arguments from
the profile, never from a project script:

| Script | Does |
|---|---|
| `scope-check.sh <base> <prefix-or-glob>...` | lists changed or untracked files outside the given paths; exit 1 if any |
| `freeze.sh freeze <file>...` / `freeze.sh verify` | prints sha256 lines; verifies them from stdin; exit 1 on any change |
| `shortcut-audit.sh <base> --scope … --tests …` | suppressions, weakened tests, swallowed errors, debt markers, removed assertions, test-count drop |
| `diff-coverage.sh <report> <base> <min> [--src-root] [--include …]` | diff-cover on a component's coverage report |

A project may list its own gate script in a component's `checks` or in `gates.extra`;
Conclave never depends on one.

### File ownership

`ownerOf(file)` in the script: first component whose `paths` match (prefix when the entry
ends with `/`, glob otherwise), else `docs-writer` for `docs.paths`, else `devops` for
`devops.paths`, else the first component in `exec.components`.

## Agent file conventions

- Frontmatter: `name`, `description` (one or two sentences, says when to use it),
  `model`, `effort`, `tools`. Read-only roles list `Read, Grep, Glob, Bash` and say in
  prose that Bash is for `git diff`, `git status` and read-only commands. Plugin agents
  cannot set `permissionMode`; write limits are stated in prose and routed by the script.
- Body order: opening paragraph (who you are, what you may edit), `## Stance` for
  adversarial roles, the role-specific method section, `## Shortcut checklist` for anyone
  who judges code, `## Checks before you report`, `## What you return`.
- No project names, paths, commands or framework names in the body. Say "the component's
  `checks`", "the stack packs named in your task", "`profile.stakes`".
- Final message is data for the orchestrator, never a human-facing summary.

## Stack packs (`skills/stack-<name>/SKILL.md`)

One per stack listed in the schema enum. Sections: `## Idioms` (what good code looks
like), `## Review checklist` (what reviewers and challengers look for), `## Testing` (how
tests are written and run, fixtures, what counts as proof), `## Tooling` (lint, type
check, build, coverage report commands and their usual flags), `## Pitfalls` (what this
stack gets wrong under pressure). Packs are loaded by `dev`, `challenger`,
`reviewer-stack`, `test-engineer` and the lead at T0/T1.

## Adding a stack

1. Add `skills/stack-<name>/SKILL.md` with the five sections.
2. Add `<name>` to the `stacks` enum in `schemas/conclave.schema.json`.
3. Add a line to the README table. No agent or script changes.
