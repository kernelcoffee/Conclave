---
name: audit
description: Whole-repository security sweep with the Conclave security reviewer and refuter, independent of any diff. One reviewer per component plus a refuter per high finding. Use periodically, before a public release, or after the threat model changes.
argument-hint: "[path]"
user-invocable: true
---
Sweep the repository (or the given path) for security defects. This is not a diff review: the reviewers read the code as it is.

Arguments: `$ARGUMENTS` (optional path; restricts the sweep to components whose `paths` contain it, or to that path alone if it matches no component).

## Steps

1. Read `.claude/conclave.json`. If it is missing, run the `conclave:init` skill first. If `security.threat_model` is a TODO, say so and ask the user to fill it before sweeping; stop.
2. Say what this spends before launching: one opus agent per component swept, plus one opus refuter per `high` finding (estimate three per component). Wait for nothing; print it and go.
3. Spawn `conclave:reviewer-security` once per component, in parallel, each with:
   - the project name, summary, stakes and the full `security` block;
   - the component entry as JSON and its stack packs to load (`conclave:stack-<name>`);
   - the instruction: sweep every file under the component's `paths` (not a diff; there may be no diff), prioritising inputs from the network, the filesystem, subprocesses, deserialisation, authentication and secrets handling; report findings in the usual shape (`file`, `line`, `severity`, `summary`, `failure_scenario`, `suggested_fix`); an empty list is valid.
4. For every `high` finding, spawn `conclave:refuter` with the finding, the threat model and the instruction to refute it by reading the code at that location and its callers, defaulting to refuted when unsure. `medium` and `low` findings are reported as-is, marked unverified.
5. Present:
   - Confirmed `high` findings: `file:line`, summary, failure scenario, suggested fix.
   - Refuted `high` findings in one line each with the reason.
   - `medium` and `low` findings grouped, one line each, marked unverified.
   - The agent count used.
6. Write nothing. For fixes, point the user at `/conclave <describe the fix>` (a finding touching auth, secrets or deletion will triage to T2 or above).
