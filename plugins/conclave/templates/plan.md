# <task title, one line>

The functional spec is what is approved; the technical spec serves it. If they conflict, the functional spec wins.

- **Task:** <the request, verbatim>
- **Date:** <YYYY-MM-DD>
- **Tier:** <the triage line: Tier T2 · backend · ~9 agents · opus×7 sonnet×2 · pace step · stages>
- **Pace:** <step | plan | auto>
- **Branch:** <branch name>
- **Status:** <planning | approved | building | reviewing | finishing | ready | done | stopped>

## Functional spec

### Why

<The problem or the need in two or three sentences: what is wrong or missing today, who it affects, what the change is meant to achieve.>

### Goals

- <outcome the feature delivers, one per line>

### Non-goals

- <what this change will not do>

### Acceptance

- [ ] <input or state, then the observable outcome>

### Decisions

- **<question>** (recommendation first; "Chosen:" filled when the user answers)
  - <recommended option> (recommended): <consequence>
  - <other option>: <consequence>
  - Chosen: <option, and why>

## Technical spec

### Current state

<How it works today, with file references.>

### Proposed model

<The recommended shape in prose: what changes, what stays, how the parts fit.>

### Alternatives

<name, summary, pros, cons for each alternative considered; "(none considered)" outside a design task>

### Migration

<How existing data, settings or callers move to the new model; "(none)" when nothing existing is affected.>

### Risks and assumptions

- <risk the reviewers should look at, or a routine call made without asking>

### Briefs

Edit these before the build stage to steer: the devs build from exactly what is written here. Every brief traces to a goal or an acceptance criterion above.

#### <component>

- Goal: <what this component must do when done>
- Files: <real paths, verified to exist or to be created>
- Steps: <ordered>
- Tests to write: <names and what each proves>
- Docs to update: <paths, or none>
- Acceptance: <what the challenger and the reviewers will check>

### Contracts

<Per pair of components that change together: paths or signatures, shapes, status codes or error types, messages; "(none)" for a single component.>

### Expected failures

<behaviour | input or state | expected outcome, one line per case; the test engineer writes tests from these without reading the implementation>

## Steps

- [ ] plan (<n> agents)
- [ ] approved by the user
- [ ] build (<n> agents)
- [ ] review (<n> agents)
- [ ] finish (<n> agents)
- [ ] commit

## Budget

- Estimated: <~n agents · model×count …>
- Actual: <plan n · build n · review n · finish n · total n>

## Log

- <YYYY-MM-DD> <decision asked and answered, brief edited by the user, finding confirmed or fixed, escalation, probe or QA result>

## Commit plan

1. <imperative title>: <files> (build-safe slices in order; the plan document is in the first)
