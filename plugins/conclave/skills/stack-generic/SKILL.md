---
name: stack-generic
description: Knowledge pack for any stack without a dedicated pack: the stack-neutral idioms, review checklist, testing, tooling and pitfalls Conclave applies everywhere. Loaded by Conclave devs, challengers, reviewers and the lead.
user-invocable: false
---
# Generic stack pack

Use when a component lists `generic` or a language with no dedicated pack. The rules here
also apply underneath every other pack.

## Idioms

- Read before you write: the files the task names and their neighbours. Match the
  patterns the codebase already uses; introduce a new one only when none fits, and say so
  in the report.
- Small functions with one job; names that say what, not how; no abbreviations the
  neighbours do not use.
- Errors are values the caller can act on: typed, with context, never swallowed; failures
  never silently become defaults.
- Boundaries validate: anything from the network, a file, the environment or a user is
  checked before use, and sizes are bounded.
- Resources are released on every path (files, sockets, locks, processes, temp dirs).
- State is explicit: no hidden globals, no action at a distance, no mutable shared state
  without a clear owner.
- Logs say what happened with the identifiers needed to find it again, and never carry
  secrets.
- Documentation and comments explain why, not what; a comment that restates the code is
  noise, a comment that lies is a defect.

## Review checklist

- Wrong result for some input: off-by-one, wrong comparison, missing branch, wrong
  default, null or empty not handled, a filter that drops the wrong items.
- A race or a lifecycle bug: shared state mutated concurrently, a resource used after
  release, cleanup that does not run on the error path.
- Unbounded growth: caches, lists, queues, retries, pages scanned, request bodies.
- Untrusted input reaching a shell, a path, a query, a template or a deserialiser without
  validation; path traversal; zip-slip; redirects to arbitrary hosts; missing timeouts.
- Secrets in code, logs, fixtures or error payloads.
- Duplicated logic where a helper exists; a new helper where one exists; dead code;
  unrelated edits and reformatting in the diff.
- A requirement from the brief quietly dropped; a deviation from the contract not reported.
- Docs or comments that claim behaviour the code does not have.
- Shortcut markers: suppressions, skipped or focused tests, loosened assertions, broad
  catches, `TODO`/`FIXME`/`HACK`, "temporary", commented-out code, sleeps hiding races.

## Testing

- Derive cases from the brief, the contract and the expected failures before reading the
  implementation: inputs that must work, inputs that must be rejected and how, boundaries,
  interrupted and concurrent cases, states in which the action must be refused.
- A case is covered only if a test asserts the outcome directly; a test that only asserts
  a mock was called does not count. A test that still passes when the change is reverted
  is not a test.
- Keep tests independent of order and of each other's state; isolate the filesystem, the
  clock and the network.
- A failing test you believe is right is a bug; report it, never weaken it.

## Tooling

- Use the project's own check commands from the profile (`component.checks`), in order,
  from the repo root; run `component.setup` once if a tool is missing.
- Never add a suppression or widen an ignore list to get a check green; fix the cause or
  report it.
- Keep CI, container and local toolchain versions pinned together; bump them in one change.

## Pitfalls

- Fixing the symptom at the call site instead of the cause in the shared code.
- "Temporary" workarounds that ship; if it cannot be done properly in the task, report it.
- Silently changing scope: a refactor nobody asked for, a dependency added without a
  reason, a file reformatted.
- Trusting a report, a comment or a commit message instead of the code.
