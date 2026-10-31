---
name: continue
description: Resume a Conclave task at the stage it stopped, in this or a later session. Reads the run state under .claude/conclave/runs/ and the task's plan document in docs/plans/, re-reads the briefs from the document so edits made there steer the next stage, and launches that stage. Use after a pause, after a session ended mid-task, or to pick one of several open tasks.
argument-hint: "[slug]"
user-invocable: true
---
Resume a task the Conclave lead paused or lost. Read `${CLAUDE_PLUGIN_ROOT}/agents/lead.md` first: you act as the lead from the stage you resume, following its per-stage procedure, pacing rules and commit proposal.

Arguments: `$ARGUMENTS` (an optional run slug).

## Steps

1. Read `.claude/conclave.json`. Read `.claude/conclave/runs/*.json`. A run is open when its plan document's Status is not `done` or `stopped`.
   - No slug and exactly one open run: use it.
   - No slug and several open runs: list them (slug, task, stage done, plan document path, last update) in one table and stop; the user picks one and calls `/conclave:continue <slug>`.
   - No open run: say so and stop.
   - A slug with no run JSON but a plan document under `docs.plans` that matches it: say that the stage state is lost (the JSON was deleted or the run came from another machine) and offer to restart from the document: the tier line and the briefs are in it, so a T2 restarts at `build` with `exec.brief` taken from the Briefs section, and a T3 restarts at `plan` unless the user says the briefs are final, in which case it restarts at `build` with those briefs as `state.briefs`. Wait for the answer.
2. Read the run JSON (`task`, `slug`, `plan_doc`, `tier`, `exec`, `stage_done`, `state`) and the plan document. The next stage is the one after `stage_done`: `null` → `plan` (T3) or `build` (T2 with `exec.brief`), `plan` → `build`, `build` → `review`, `review` → `finish`, `finish` → the commit proposal.
3. Re-read the Briefs section of the plan document and copy each `### <component>` body into `state.briefs[<component>]` (for a T2 with no state yet, into `exec.brief`). Say in one line whether the briefs changed since the last stage. Pass `state` otherwise unchanged.
4. Run the preflight from `lead.md` for the branch and the tree (the branch in the document must be the current one; a dirty tree is reported, not stashed).
5. Print the triage line from the document, the next stage and its estimated agents, then launch it with `exec.stage` and `exec.state` as `lead.md` describes, and continue the per-stage procedure: update the document, save the run JSON, pause when the pace says so.

Write nothing to the repository other than the plan document and the run JSON until the stage returns.
