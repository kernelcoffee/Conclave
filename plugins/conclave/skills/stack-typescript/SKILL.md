---
name: stack-typescript
description: Knowledge pack for strict TypeScript (Node and browser, Vite, vitest): idioms, review checklist, testing, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead.
user-invocable: false
---
# TypeScript stack pack

Applies to any TypeScript code: frontends, Node services, CLIs, shared libraries. React
specifics live in `stack-react`; load both when the component lists both.

## Idioms

- `strict: true` and the checker respected: no `any`, no `as X` where a narrowing would
  do, no `!` non-null assertions to silence the checker, `unknown` at boundaries narrowed
  before use, `satisfies` to check shapes without widening.
- Types that mirror the backend: one file or directory of API types that match the server
  schemas field for field, unions of string literals for enums, `null` where the server
  sends it, ISO strings for datetimes, a typed envelope (`ApiResponse<T>`) for every call.
- Discriminated unions handled exhaustively with a `never` check in the default branch
  (event types, message kinds, state machines).
- Async: every promise awaited or returned; no floating promises in effects or handlers;
  results aborted or ignored when the caller is gone (`AbortController`, a cancelled flag);
  errors routed to an error state or a notification, never swallowed.
- Module boundaries: network access in one client module, pure helpers in a `lib/` or
  `utils/` module with no framework import so tests load them without rendering, types
  separate from runtime code when they are shared.
- Imports through the project alias (`@/`) when one exists; ES modules; named exports;
  no default export of anonymous values.
- Dependencies: no new package without a reason stated in the report; pinned versions in
  the lockfile; Node version pinned in `.nvmrc` and matched by CI and containers.

## Review checklist

- `any`, `as any`, `as unknown as X`, `@ts-ignore`, `@ts-expect-error` without a
  reason, `eslint-disable` comments, a rule widened in `eslint.config.js` or `tsconfig`.
- A type that drifts from the backend schema: an optional field typed required, an enum
  widened to `string`, a `null` the server sends typed away.
- A `fetch` or client call outside the client module; an envelope read without handling
  the failure branch.
- A floating promise; a `.then` without a `.catch` or an `await` in a `try`; an async
  handler whose rejection nobody sees.
- Non-exhaustive `switch` on a union; a new variant added without updating every consumer.
- Duplicated helpers: a second formatter, date helper or URL builder is a finding.
- Dead exports, unused parameters, commented-out code.
- Browser globals used in modules that run in Node or in a test environment without setup.
- Tests: `.only` or `.skip` added, `expect` assertions removed, `waitForTimeout` or `sleep`
  hiding a race, a mock of the module under test.

## Testing

- vitest for units and modules (`*.test.ts` next to the module or under `tests/`), jsdom
  environment when DOM APIs are needed; `vi.mock` for modules the unit depends on, never
  the unit itself; `vi.useFakeTimers` for time; `fetch` mocked on `globalThis` or through
  the client module.
- Prove behaviour: assert on the returned value, the DOM or the request made, not on
  a spy being called.
- Playwright for flows across pages when the project has it; stub the API with route
  handlers so no backend is needed in the smoke tier; the full tier may start real services.
- Coverage report for the gate: `vitest run --coverage` with the `cobertura` or `lcov`
  reporter configured in `vitest.config.ts`, then
  `bin/diff-coverage.sh <report> <base> <min> --src-root <dir> --include <globs>`,
  restricted to the logic modules vitest can see when components are covered by e2e.

## Tooling

- Type check: `tsc --noEmit` (or `tsc -b` for project references); lint: `eslint .`;
  format: prettier if configured.
- Build: `vite build` (includes a type check when `tsc -b && vite build` is the script).
- Run checks through `npm run <script>` or `npm --prefix <dir> run <script>` so the
  project's config applies; `npm ci` when `node_modules` is missing.
- Tests: `vitest run` (not watch mode) in checks; one file: `vitest run path/to/x.test.ts`.

## Pitfalls

- A `catch (e) {}` that swallows a network failure and leaves the UI in a loading state.
- Narrowing lost through a closure or after an `await`; re-check instead of asserting.
- `JSON.parse` output typed by assertion instead of validated (zod or a hand-written guard).
- Date handling in local time when the backend speaks UTC; use ISO strings end to end and
  format at the edge.
- Node version drift between `.nvmrc`, CI and the container image; bump them together.
- A lockfile not updated with `package.json`, so CI installs something else.
- Tests that depend on execution order or on a shared module-level cache.
