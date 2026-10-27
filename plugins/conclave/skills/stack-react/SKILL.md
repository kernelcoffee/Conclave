---
name: stack-react
description: Knowledge pack for React 18/19 with Vite, TanStack Query, optional Zustand and Tailwind: idioms, review checklist, testing, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead.
user-invocable: false
---
# React stack pack

Load together with `stack-typescript`. Covers function components and hooks, effects and
cleanups, server state with TanStack Query, client state with Zustand or context, forms,
WebSocket providers, Tailwind layout and theming.

## Idioms

- Function components with hooks; hooks called unconditionally at the top level; `enabled`
  guards instead of conditional hook calls.
- Server state only through query hooks: stable query keys that include every parameter,
  mutations that invalidate or update the queries they affect, loading and error read from
  the query rather than tracked by hand. Client-only state in a store or context, never
  server data copied into it.
- Derived values computed during render (or memoised), not stored in state; no state
  duplicated from props; refs for values that must not trigger renders; updater functions
  when the next state depends on the previous.
- Effects: data fetching lives in hooks, not effects; every effect that subscribes, starts
  a timer or opens a socket returns a cleanup; behaviour survives StrictMode's double
  mount and unmount; dependency arrays are correct and the `react-hooks` lint rules stay on.
- One WebSocket connection owned by a provider; consumers through context hooks; handlers
  registered and removed symmetrically.
- Shared components (buttons, inputs, toggles, cards, badges, modal, toasts, skeletons)
  reused instead of one-off markup; a form initialised from loaded data in an inner
  component remounted by `key`, rather than syncing state in an effect.
- Rendering: stable keys (ids, never indexes), no new object or function identities passed
  to memoised children, lists paginated or capped, chart data memoised.
- Every fetch has loading, empty and error states; every async action shows a pending
  state and then success feedback or the server's error message; destructive actions
  confirm; controls that cannot apply are disabled with a visible reason.
- Tailwind classes that work in both the dark and the light theme; rows wrap on a narrow
  screen; tables scroll inside their container; nothing overflows the page.

## Review checklist

- A hook called conditionally or in a loop; a dependency array silenced with a comment.
- An effect without cleanup for a timer, subscription, socket handler or abort controller;
  an effect that sets state from props (derive instead).
- A mutation that does not invalidate the queries it changes; a query key missing a
  parameter so two screens share stale data.
- Server data stored in a Zustand store or `useState`; derived values stored in state.
- A `success: false` envelope rendered as data; an error swallowed into a permanent
  spinner.
- Keys by index; a new inline object or callback passed to a memoised child on every render.
- Markup duplicating a shared component; colours or classes that only work in one theme;
  layouts that overflow at 400px wide.
- Icon-only buttons without an accessible name; colour as the only status signal; inputs
  without labels.
- A new dependency without a reason; browser globals in a module vitest loads without a
  DOM environment.
- Tests that mock the hook under test, assert only that a mock was called, or use
  `waitForTimeout` to hide a race.

## Testing

- vitest with jsdom and Testing Library: hooks with `renderHook` and a wrapper that
  provides the QueryClient (and any router or theme provider); components with a shared
  `render` helper that wraps providers.
- Mock `fetch` on `globalThis` or the API client module; never the hook or component under
  test. Use `findBy*` queries and `waitFor` for async UI, not timers.
- Assert on what the user sees: text, roles, disabled state, the request that was sent.
- Playwright specs for flows across pages, stubbing the API with route handlers; follow an
  existing degraded-API spec for failure paths.
- Coverage: vitest covers logic modules (`hooks`, `lib`, `api`, `stores`, `utils`); `.tsx`
  pages and components are covered by Playwright, which produces no coverage, so the diff
  gate is restricted with `--include` to the logic modules.

## Tooling

- Vite dev server (`npm run dev`), proxying `/api` and `/ws` to the backend in development;
  `npm run build` runs `tsc -b && vite build`.
- Lint: `eslint .` with `react-hooks` and `react-refresh` plugins; type check: `tsc --noEmit`.
- Tests: `vitest run`; e2e: `npx playwright test` with the project's config, which may start
  the dev server itself.

## Pitfalls

- StrictMode double mount leaking a second socket or timer because the cleanup is missing
  or the effect captured a stale ref.
- An `async` function passed directly to `useEffect` (returns a promise, not a cleanup).
- Setting state after unmount from a resolved promise; guard with an abort flag.
- Form state initialised once from `undefined` because the query had not loaded; remount
  by `key` when data arrives.
- Query cache shared across tests because the QueryClient is module-level; create one per
  render in the test wrapper.
- A Tailwind class built by string concatenation that the JIT compiler never sees; use
  full class names.
- Mobile layout broken by a fixed-width sidebar or a table without an overflow container.
