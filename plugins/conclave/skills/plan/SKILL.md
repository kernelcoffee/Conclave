---
name: plan
description: Plan a task with the Conclave pm and architect only, no code. Produces the spec, acceptance criteria, open decisions, per-component briefs, contracts and the expected-failure matrix. Use before a large change, or to get a second opinion on scope.
argument-hint: <task>
user-invocable: true
---
Plan the task below with the `pm` and `architect` roles; write no code.

Task: `$ARGUMENTS` (if empty, ask for it in one line and stop).

## Steps

1. Read `.claude/conclave.json`. If it is missing, run the `conclave:init` skill first.
2. Build `exec`: `{ task: <the task verbatim>, components: <component names you think are touched, may be empty>, base: profile.base, plugin_root: "${CLAUDE_PLUGIN_ROOT}" }`.
3. Say in one line that this spends two agents on the session model (pm, then architect), then launch:

```
Workflow({ name: "conclave:plan", args: { profile: <profile object>, exec: <exec> } })
```

If the name is not registered, launch with `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/plan.js"` and the same args.

4. Present the result:
   - The spec: summary, goals, non-goals, acceptance criteria as a list.
   - Open decisions, each with its options and the recommendation first. If any exist, the plan stopped before the architect; ask the user with AskUserQuestion and relaunch with `exec.decisions` and `exec.proceed: true` once answered.
   - Per component: the brief (Goal, Files, Steps, Tests to write, Docs to update, Acceptance).
   - Contracts, the expected-failure matrix, risks, assumptions, and any ad-hoc specialists the architect defined.
5. End with the one-line `/conclave --tier 3 <task>` command that would build it, and the agent count that tier would spend.

Write nothing to the repository.
