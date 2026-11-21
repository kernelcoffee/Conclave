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
   - A slug with no run JSON but a plan document under `docs.plans` that matches it: say that the stage state is lost (the JSON was deleted or the run came from another machine) and offer to restart from the document, taking the tier from its Tier line. A document whose Status is `planning` has not been approved: it restarts through the `planning` rules in step 2 (at T2 the analysis checkpoint first when its step is present and unticked and `plan` is unticked, then the approval gate), and `build` is never offered from it. A document at `approved` or later restarts from its briefs: a T2 at `build` with `exec.brief` taken from the Briefs section, and a T3 at `plan` unless the user says the briefs are final, in which case at `build` with those briefs as `state.briefs`. Wait for the answer.
2. Read the run JSON (`task`, `slug`, `plan_doc`, `tier`, `exec`, `stage_done`, `state`) and the plan document. The next stage is the one after `stage_done`: `null` → `plan` (T3) or `build` (T2 with `exec.brief`), `plan` → `build`, `build` → `review`, `review` → `finish`, `finish` → the commit proposal. A run whose document Status is `planning` (for example one written by `/conclave:plan`) has not been approved:
   - At T2, when the Steps list holds the `analysis checkpoint` step unticked and `plan` unticked, resume at the analysis checkpoint in `lead.md`, not at the approval gate: write the Analysis if it still holds the template's placeholders, show its summary and Unknowns, and wait for the user's confirmation; then write the specs and go on to the approval gate.
   - Otherwise (the step is ticked, whether confirmed or skipped, including a plan-only run that marked it `analysis checkpoint: skipped, plan-only run`; `plan` is ticked, so the plan stage already wrote the specs and they are never rewritten; the tier is T1 or T3, where the checkpoint is part of the approval gate, or the document has no such step because it was written before the step existed and is treated as past the checkpoint): at T1 and T2 write whatever still holds the template's placeholders, the Analysis first at T1 (at T3 the specs come from the `plan` stage), then show the summary the approval gate in `lead.md` describes, and wait for the user's approval.
   - On approval tick the steps the approval gate ticks, set Status `approved`, and only then launch `build`. Never launch `build` from `planning`.
3. Re-read the Briefs section of the plan document and copy each `#### <component>` body (under Technical spec, Briefs) into `state.briefs[<component>]` (for a T2 with no state yet, into `exec.brief`). Say in one line whether the briefs changed since the last stage. Pass `state` otherwise unchanged.
4. Run the preflight from `lead.md` for the branch and the tree (the branch in the document must be the current one; a dirty tree is reported, not stashed).
5. Print the triage line from the document, the next stage and its estimated agents, then launch it with `exec.stage` and `exec.state` as `lead.md` describes, and continue the per-stage procedure: update the document, save the run JSON, pause when the pace says so.

Write nothing to the repository other than the plan document and the run JSON until the stage returns.
