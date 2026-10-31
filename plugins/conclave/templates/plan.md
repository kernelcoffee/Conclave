# <task title, one line>

- **Task:** <the request, verbatim>
- **Date:** <YYYY-MM-DD>
- **Tier:** <the triage line: Tier T2 · backend · ~9 agents · opus×7 sonnet×2 · stages>
- **Pace:** <step | plan | auto>
- **Branch:** <branch name>
- **Status:** <planning | building | reviewing | finishing | ready | done | stopped>

## Why

<The problem or need in two or three sentences: what is wrong or missing today, who it affects, what the change is meant to achieve.>

## Spec

<Goals, non-goals and acceptance criteria. Acceptance criteria are testable statements, one per line.>

- Goals: <outcome>
- Non-goals: <what this change will not do>
- Acceptance:
  - [ ] <input or state, then the observable outcome>

## Design

<The approach in a few sentences. For a design duel: the chosen plan, which developer proposed it, and why the judge or the pair chose it.>

## Briefs

Edit these before the build stage to steer: the devs build from exactly what is written here.

### <component>

- Goal: <what this component must do when done>
- Files: <real paths, verified to exist or to be created>
- Steps: <ordered>
- Tests to write: <names and what each proves>
- Docs to update: <paths, or none>
- Acceptance: <what the challenger and the reviewers will check>

## Contracts

<For each pair of components that change together: paths or signatures, request and response shapes, status codes or error types, messages. "(none)" for a single component.>

## Expected failures

<One line per case: behaviour | input or state | expected outcome. The test engineer writes tests from these without reading the implementation.>

## Steps

- [ ] plan (<n> agents)
- [ ] build (<n> agents)
- [ ] review (<n> agents)
- [ ] finish (<n> agents)
- [ ] commit

## Budget

- Estimated: <~n agents · model×count …>
- Actual: <plan n · build n · review n · finish n · total n>

## Log

- <YYYY-MM-DD> <decision asked and answered, finding confirmed or fixed, escalation, probe or QA result, brief edited by the user>

## Commit plan

<Ordered build-safe slices, each with an imperative title and its files. The plan document is part of the first slice.>

1. <title>: <files>
