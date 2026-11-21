---
name: plan
description: Write the plan document for a task without building anything: an analysis (request, current state, constraints, unknowns), then the functional spec (why, goals, non-goals, acceptance, decisions with their consequences), then the technical spec (proposed model, alternatives, briefs, contracts, failure matrix). With --design, a design study proposes the model and argues the alternatives before the spec. Use before a large change, for a redesign, or to get a reviewable plan to approve.
argument-hint: "[--design] <task>"
user-invocable: true
---
Produce the plan document for the task below with the `pm` and `architect` roles, and nothing else. Read `${CLAUDE_PLUGIN_ROOT}/agents/lead.md` first: you follow its plan-document procedure, its decision handling and its functional-over-technical rule, but you stop at the approval gate; you never launch a build.

Arguments: `$ARGUMENTS`. `--design` turns design mode on; the rest is the task, verbatim. If the task is empty, ask for it in one line and stop.

## Steps

1. Read `.claude/conclave.json`. If it is missing, run the `conclave:init` skill first. Run the preflight checks from `lead.md` that concern the branch (a plan-only run may stay on any branch; say which).
2. Triage as `lead.md` says and print the triage line, with `· design` when design mode is on. The tier decides what the document asks for; nothing is built here. Decide design mode yourself too: a task that redefines how something works, or a new feature with more than one defensible shape, gets it even without the flag; say so.
3. Create the plan document and the run JSON as `lead.md` describes (template, slug, and the `.gitignore` lines `lead.md` names: `.claude/conclave/` and, unless plans are committed, the plans directory; when that directory tracks other documents, the question `lead.md` puts to the user; the one-time notice when plan documents are already tracked there; and the `git check-ignore` check), Status `planning`, with one extra key in the run JSON: `"plan_only": true`. Write no Analysis yourself, whatever the tier: the architect writes it in step 4. This is the plan-only rule under "The analysis checkpoint" in `lead.md`, which is its T3 rule at any tier.
4. Say what this spends before launching: the architect's analysis, pm and architect on the session model (three calls), plus the design study in design mode (four). Then launch the analysis:

```
Workflow({ name: "conclave:plan-team", args: { profile: <profile object>, exec: { stage: "analysis", task: <task>, components: <names you think are touched, may be empty>, base: profile.base, plugin_root: "${CLAUDE_PLUGIN_ROOT}" } } })
```

If the name is not registered, launch with `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/plan-team.js"` and the same args, here and in step 5.

On `stage-done`, fill the Analysis from `analysis` as `lead.md` says for T3 under "The analysis checkpoint", save `stage_done: "analysis"` and `state` in the run JSON, re-triage (it changes the Tier line only), and hold the checkpoint it describes: the stop happens at every pace, and no spec is written before the user confirms. A correction that needs code the architect did not read relaunches `stage: "analysis"` with the correction in `exec.decisions` and the saved `state` as `exec.state`.
5. On confirmation mark the step `- [x] analysis checkpoint: confirmed by the user`, log it, re-read the Analysis section into `state.analysis` (each subsection into the field of the same name; an edit in the document wins), save that `state` in the run JSON, and launch the plan without `exec.proceed` and without `exec.decisions` (a correction belongs to the analysis stage only and is already in `state.analysis`; plan-team would read it as answers to questions it has not asked yet):

```
Workflow({ name: "conclave:plan-team", args: { profile: <profile object>, exec: { stage: "plan", state: <saved state>, task: <task>, components: <names>, base: profile.base, plugin_root: "${CLAUDE_PLUGIN_ROOT}", mode: "design" } } })
```

Omit `mode` outside design mode.

6. `needs-human` (from either launch: an analysis that came back empty, design decisions, or pm or architect decisions): present each decision with AskUserQuestion, every option with its consequence, the recommendation first. Write the question, the options and `Chosen: <option>, <why>` under Decisions in the document, log it, then relaunch the same stage with the saved `state`, its `state.analysis` re-read from the Analysis section before every `plan` relaunch (an edit in the document wins). What else the relaunch carries follows from the content of the stop, as `lead.md` says under `needs-human`: when `decision_request.context` carries `decisions` or `needs_decision`, `exec.decisions` set to the answers and `exec.proceed: true`; for any other stop (an analysis that came back empty, the only empty answer plan-team returns as a stop), relaunch without `exec.proceed` and with `exec.decisions` exactly as the launch that stopped carried it, so a revision keeps its correction and the relaunched plan still stops on every open decision. Every stop is handled this way. An empty design study, pm or architect answer is not a stop: plan-team fails with an error and returns nothing. Log it, tell the user which call came back empty, and on their word relaunch `stage: "plan"` with the same `exec` and the `state` saved in the run JSON, which keeps the confirmed analysis, so only the study, the pm and the architect run again. Repeat until the plan launch returns `accepted`.
7. Fill the document from the result: the Functional spec from `spec` (why, goals, non-goals, acceptance; decisions already written), the Technical spec from `design_study` when present (problems folded into Why, proposed model, alternatives, migration, risks) and from `plan` (briefs per component, contracts, expected failures, risks and assumptions). Tick `plan` in Steps with the agents used (`agents.n`, the analysis call included); the analysis checkpoint step is marked confirmed, never skipped. Save the run JSON with `stage_done: "plan-team"` and, as `state`, the returned `state` with the result's `spec`, `design_study` and `plan` added under those names and its `components` kept only where they name a component of the profile: plan-team's own `state` holds only `analysis` and `agents`, and `conclave:dev-team` resumes from these. So far the analysis, the design study in design mode, the pm and the architect have run; after approval, `/conclave:continue` launches the `plan` stage of `conclave:dev-team` on this `state`, which runs only the design duel and the consults (security, UX, devops, the architect's consultants) without writing the specs again, and then the build. Write the Budget estimate for those stages. Status stays `planning`: approval is the user's next move, not yours.
8. End with the document path, a five-line summary of the Functional spec, the agent count used, and the one line that builds it once approved: `/conclave:continue <slug>` (or `/conclave --tier 3 <task>` when the user prefers to start again).

Writes only the plan document and the run JSON.
