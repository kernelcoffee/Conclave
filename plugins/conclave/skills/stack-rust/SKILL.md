---
name: stack-rust
description: Knowledge pack for Rust (2024 edition, 2021 still common) crates, binaries and tokio services: idioms, review checklist, testing, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead.
user-invocable: false
---
# Rust stack pack

Applies to Rust crates and binaries, synchronous or async on tokio, built with cargo.
The crate's `edition` in `Cargo.toml` decides the language rules; new crates use 2024,
and 2021 crates are still common. Never change a crate's edition as a side effect of a
task; an edition migration is its own change (`cargo fix --edition`, then review).
`rust-version` in `Cargo.toml` is the minimum supported Rust; do not use APIs newer than
it.

## Idioms

- Ownership tells the story: borrow (`&T`, `&mut T`) by default, take ownership only when
  the callee stores or consumes the value, return owned values from constructors; `Cow`
  when a function sometimes needs to allocate; avoid `clone()` to satisfy the borrow
  checker without a reason stated.
- Errors: a library crate defines its error enum with `thiserror` and returns
  `Result<T, Error>`; a binary may use `anyhow` with `.context("what was being done")`;
  no `unwrap()`/`expect()` on fallible paths in library code; `?` everywhere else;
  panics only for programmer errors, documented with `# Panics`.
- Types encode invariants: newtypes for ids and units, enums for closed sets, builders for
  many optional fields, `NonZero*` and `std::num` types where zero is invalid, `#[must_use]`
  on results that must not be dropped.
- Traits for behaviour, generics for static dispatch, `dyn Trait` when heterogeneity or
  compile time matters; `impl Trait` in argument and return position for simplicity.
- Iterators and combinators over index loops; `collect` into the type you need; no
  intermediate `Vec` when an iterator chain will do.
- Async: tokio runtime chosen once in `main`; no blocking calls (`std::fs`, `std::thread::sleep`,
  CPU work) inside async fns, use `spawn_blocking` or `tokio::fs`; every `JoinHandle`
  awaited or detached on purpose with its error handled; cancellation-safe `select!` arms;
  bounded channels; `Arc<Mutex<T>>` only when a channel or an actor does not fit, and the
  lock never held across an `.await` (use `tokio::sync::Mutex` only if it must be).
- `unsafe` is rare, minimal, wrapped in a safe API, and every block has a `// SAFETY:`
  comment stating the invariant it relies on.
- Modules small and named for what they contain; `pub(crate)` by default; a `prelude`
  only for a library with many user-facing types; docs on every public item with an
  example that compiles as a doctest.

## Review checklist

- Edition 2024 rules, in a 2024 crate: `extern` blocks are `unsafe extern` and their items
  say `safe` or `unsafe`; `#[no_mangle]`, `#[export_name]` and `#[link_section]` are
  written `#[unsafe(...)]`; `std::env::set_var` and `remove_var` are `unsafe` and need a
  `// SAFETY:` comment; references to `static mut` are a hard error (use atomics,
  `Mutex`, `OnceLock` or `&raw const`); unsafe operations inside an `unsafe fn` need
  their own `unsafe {}` block; `impl Trait` in return position captures every in-scope
  lifetime unless narrowed with `use<..>`; `gen` is a reserved keyword.

- `unwrap()`, `expect()`, `panic!`, `todo!`, `unimplemented!` on a reachable path in
  library code or request handling.
- `clone()` to dodge a borrow error; `Rc`/`Arc` where a borrow would do; `String` where
  `&str` suffices in a parameter.
- An error type that loses the source (`map_err(|_| ...)`), a `Box<dyn Error>` in a
  library API, a `.context` missing where the message would be meaningless.
- `unsafe` without a `SAFETY` comment, or a safe wrapper whose invariant the caller can
  break; `transmute`; raw pointer arithmetic that could alias.
- Blocking inside async; a `std::sync::Mutex` guard held across `.await`; an unbounded
  channel; a `select!` arm that is not cancellation safe; a spawned task whose error
  nobody reads.
- Integer overflow on arithmetic with untrusted input (use `checked_*`/`saturating_*`);
  `as` casts that truncate; indexing with untrusted values instead of `.get()`.
- Deadlocks from lock ordering; `RefCell` borrows that can panic at runtime.
- `#[allow(...)]` added to silence clippy instead of fixing; clippy level lowered in
  `Cargo.toml` or `lib.rs`.
- Public API changes without doc updates; a `pub` item that should be `pub(crate)`.
- Tests: `#[ignore]` added, an assertion replaced by a `let _ =`, a test that only checks
  `is_ok()` where the value matters.

## Testing

- Unit tests in a `#[cfg(test)] mod tests` next to the code; integration tests under
  `tests/` using only the public API; doctests on public items.
- Async tests with `#[tokio::test]` (multi-thread flavor when the code spawns); time
  controlled with `tokio::time::pause()` and `advance`, never real sleeps.
- Property tests with `proptest` for parsers and arithmetic; snapshot tests with `insta`
  for serialised output; `assert_matches!` for enums.
- Filesystem through `tempfile::tempdir()`; network through a trait and a fake, or
  `wiremock` for HTTP.
- Coverage report for the gate: `cargo llvm-cov --cobertura --output-path coverage.xml`
  (preferred) or `cargo tarpaulin --out Xml`, then `bin/diff-coverage.sh coverage.xml <base> <min>`.

## Tooling

- `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`,
  `cargo test` (add `--workspace` for workspaces); `cargo doc --no-deps` to catch broken
  doc links; `cargo deny check` or `cargo audit` when the project has it.
- Edition and MSRV pinned in `Cargo.toml`; `rust-toolchain.toml` when a toolchain is
  required; the lockfile committed for binaries.
- `cargo nextest run` where installed for faster, isolated test runs.

## Pitfalls

- Edition 2024 temporary scopes: the temporaries in an `if let` scrutinee and in a block's
  tail expression are dropped earlier than in 2021, so a lock guard or `RefCell` borrow
  that used to live through the `else` branch or the end of the block no longer does;
  a change that moves code between crates of different editions can change drop order.

- `.await` inside a `std::sync::Mutex` guard, deadlocking the runtime under load.
- `tokio::spawn` of a future that is not `Send` because it holds a `Rc` or a non-Send guard.
- Holding a `RefCell` borrow across a call that re-borrows.
- `String` formatting in hot loops; use `write!` into a buffer.
- Implicit `Drop` order causing a channel receiver to close before the sender finishes.
- Forgetting `#[serde(deny_unknown_fields)]` or default handling, so config typos pass
  silently.
- A `build.rs` that does network access or writes outside `OUT_DIR`.
