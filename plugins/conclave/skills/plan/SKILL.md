---
name: plan
description: Write the plan document for a task without building anything: functional spec (why, goals, non-goals, acceptance, decisions with their consequences) first, technical spec (current state, proposed model, alternatives, briefs, contracts, failure matrix) second. With --design, a design study proposes the model and argues the alternatives before the spec. Use before a large change, for a redesign, or to get a reviewable plan to approve.
argument-hint: "[--design] <task>"
user-invocable: true
---
Produce the plan document for the task below with the `pm` and `architect` roles, and nothing else. Read `${CLAUDE_PLUGIN_ROOT}/agents/lead.md` first: you follow its plan-document procedure, its decision handling and its functional-over-technical rule, but you stop at the approval gate; you never launch a build.

Arguments: `$ARGUMENTS`. `--design` turns design mode on; the rest is the task, verbatim. If the task is empty, ask for it in one line and stop.

## Steps

1. Read `.claude/conclave.json`. If it is missing, run the `conclave:init` skill first. Run the preflight checks from `lead.md` that concern the branch (a plan-only run may stay on any branch; say which).
2. Triage as `lead.md` says and print the triage line, with `· design` when design mode is on. The tier decides what the document asks for; nothing is built here. Decide design mode yourself too: a task that redefines how something works, or a new feature with more than one defensible shape, gets it even without the flag; say so.
3. Create the plan document and the run JSON exactly as `lead.md` describes (template, slug, `.claude/conclave/` in `.gitignore`), Status `planning`.
4. Say what this spends before launching: pm and architect on the session model, plus the architect once more for the design study in design mode. Then launch:

```
Workflow({ name: "conclave:plan-team", args: { profile: <profile object>, exec: { task: <task>, components: <names you think are touched, may be empty>, base: profile.base, plugin_root: "${CLAUDE_PLUGIN_ROOT}", mode: "design" } } })
```

Omit `mode` outside design mode. If the name is not registered, launch with `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/plan-team.js"` and the same args.

5. `needs-human` (design decisions, or pm or architect decisions): present each decision with AskUserQuestion, every option with its consequence, the recommendation first. Write the question, the options and `Chosen: <option>, <why>` under Decisions in the document, log it, then relaunch with `exec.decisions` set to the answers and `exec.proceed: true`. Repeat until the run returns `accepted`.
6. Fill the document from the result: the Functional spec from `spec` (why, goals, non-goals, acceptance; decisions already written), the Technical spec from `design_study` when present (current state, problems folded into Why, proposed model, alternatives, migration, risks) and from `plan` (briefs per component, contracts, expected failures, risks and assumptions). Tick `plan` in Steps with the agents used; write the Budget estimate for the build. Status stays `planning`: approval is the user's next move, not yours.
7. End with the document path, a five-line summary of the Functional spec, the agent count used, and the one line that builds it once approved: `/conclave:continue <slug>` (or `/conclave --tier 3 <task>` when the user prefers to start again).

Writes only the plan document and the run JSON.
