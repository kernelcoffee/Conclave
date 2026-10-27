# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What Conclave is

A Claude Code plugin (plus its own single-plugin marketplace) that ships a full software
team as subagents and a lead that sizes each task before spending tokens. It generalises
the adversarial dev team that used to be copied into Lectern and SteamSelfGifter.
`docs/design.md` is the contract between the pieces; read it before changing an agent,
a skill or a workflow.

## Layout

```
.claude-plugin/marketplace.json     marketplace with one plugin, source ./plugins/conclave
plugins/conclave/
  .claude-plugin/plugin.json        manifest
  settings.json                     "agent": "conclave:lead"
  agents/*.md                       one file per role; lead.md is the orchestrator; verifier and
                                    test-auditor are the mechanical and adversarial gatekeepers
  skills/<command>/SKILL.md         /conclave, /conclave:init, :plan, :review, :release, :audit
  skills/stack-<name>/SKILL.md      stack knowledge packs (not user-invocable)
  workflows/dev-team.js             the pipeline; shaped by exec from the lead
  workflows/review.js, plan.js      subsets
  bin/shortcut-audit.sh             generic gate scripts QA and the verifier run
  bin/diff-coverage.sh
  bin/scope-check.sh                changed files must stay under allowed prefixes
  bin/freeze.sh                     sha256 freeze and verify of the contract tests
  templates/conclave.json           profile template
  schemas/conclave.schema.json      profile schema
docs/design.md                      tiers, model policy, interfaces, conventions
```

## Commands

```bash
CLAUDE=~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude   # or `claude` if on PATH
$CLAUDE plugin validate plugins/conclave        # manifest and layout
$CLAUDE plugin validate .                       # marketplace
$CLAUDE --plugin-dir plugins/conclave           # try the plugin in a session; /reload-plugins after edits
bash -n plugins/conclave/bin/*.sh && shellcheck plugins/conclave/bin/*.sh
```

Workflow scripts use top-level `return`, which `node --check` rejects on its own. To
syntax-check one, prefix a stub line defining `args, agent, parallel, pipeline, phase,
log, budget`, wrap the body in `async function main(){…}`, and replace `export const meta`
with `const meta`, in a scratch copy.

## Conventions

- Agent bodies carry no project names, paths, commands or framework names. Anything
  project-specific comes from `.claude/conclave.json` through the prompt, or from a stack
  pack. See "Agent file conventions" in `docs/design.md`.
- The script never decides tier, rounds, lenses or models; the lead does, in `exec`.
  Keep that split when adding a phase.
- Return shapes (`SPEC`, `PLAN`, `DEV`, `CHALLENGE`, `FINDINGS`, `VERDICT`, `TESTS`,
  `DOCS`, `QA`) are shared by the scripts and the agents' "What you return" sections.
  Change both or neither.
- Adding a stack: a `skills/stack-<name>/SKILL.md` with the five sections, the enum entry
  in the schema, a README row. No agent or script changes.
- Plugin agents ignore `permissionMode`, `hooks` and `mcpServers`. Write limits are prose.
- Subagents never commit. The lead proposes a commit and waits.
- Escalation is uniform: a workflow returns status `needs-human` with `decision_request`
  from any phase; the lead handles every one the same way.

## Git

- Conventional commit subjects with a scope: `feat(agents): …`, `fix(workflow): …`,
  `docs: …`, `chore: …`.
- Bump `version` in both `plugins/conclave/.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json` together.
