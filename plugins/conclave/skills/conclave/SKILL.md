---
name: conclave
description: Run a task through the Conclave team. The lead sizes it into a tier (T0 inline to T3 full adversarial pipeline), prints the agent count and model mix, then does it or dispatches the dev-team workflow. Use for any change on a project with a .claude/conclave.json profile.
argument-hint: <task> [--tier N] [--rounds N] [--contract] [--duel] [--dry-run]
user-invocable: true
---
Read `${CLAUDE_PLUGIN_ROOT}/agents/lead.md` and act as that agent for the task below. Pass `${CLAUDE_PLUGIN_ROOT}` as `exec.plugin_root` whenever you launch a workflow or spawn a role.

## Arguments

```
$ARGUMENTS
```

Parse flags out of the arguments first; the rest is the task text, verbatim:

- `--tier N` (0 to 3): the user's tier wins over your triage. Say that you are using the forced tier.
- `--rounds N`: sets `exec.rounds` for the challenge and review loops.
- `--contract`: sets `exec.contract` to true (test-first contract tests, audited and frozen before the build). T3 only: if your triage lands lower, raise the tier to T3 and say so.
- `--duel`: sets `exec.design` to `"duel"` (two dev designs, cross-critique, the architect judges). T3 only, same rule.
- `--dry-run`: run the triage only. Print the triage line, the `exec` object you would launch with (or "inline" for T0/T1 with the files you would touch), the estimated agent count and model mix, then stop. Write nothing, spawn nothing.

If the task text is empty, ask for it in one line and stop.

## Then

Follow `lead.md` end to end: profile, triage line, execution at the chosen tier, commit proposal. The profile is `.claude/conclave.json`; when it is missing, run the `conclave:init` skill first.
