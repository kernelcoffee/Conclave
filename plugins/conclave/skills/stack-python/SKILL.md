---
name: stack-python
description: Knowledge pack for Python 3.11+ (typing, asyncio, packaging, pytest): idioms, review checklist, testing, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead.
user-invocable: false
---
# Python stack pack

Applies to any Python 3.11+ code: services, CLIs, bots, workers, libraries. Framework
specifics (FastAPI, SQLAlchemy, APScheduler) live in `stack-fastapi`; load both when the
component lists both.

## Idioms

- Modern syntax: `X | None` instead of `Optional[X]`, builtin generics (`list[str]`,
  `dict[str, int]`), `match` where it reads better than an `if` chain, `type` statements
  and PEP 695 generics (3.12+) where they help, dataclasses or pydantic models instead of
  dicts for structured data, `enum.StrEnum` for closed string sets.
- `pathlib.Path` over string paths; f-strings; `enumerate`/`zip`; comprehensions when they
  stay on one line; no mutable default arguments; no shadowed builtins.
- Precise annotations on every function. `Any` is a defect unless the value really is
  untyped at the boundary (JSON from the network) and is narrowed right after.
- Exceptions: catch the narrowest type, re-raise with `from`, define domain errors in one
  module and raise those where a caller or middleware must branch. Error messages name
  what went wrong without carrying secrets.
- Resources: `with` / `async with` for files, sessions, clients, locks; no partial writes
  left behind (write to a temp file, then rename).
- Logging through the standard `logging` or structlog with key-value fields, never print,
  never f-string messages that pre-render expensive values.
- asyncio: no blocking IO or CPU work on the event loop (`time.sleep`, sync HTTP, heavy
  parsing); `asyncio.to_thread` for anything heavy; every task tracked or awaited;
  cancellation handled; no fire-and-forget without an error handler; one subprocess per
  job via `asyncio.create_subprocess_exec`, never a thread per job.
- Packaging: `pyproject.toml` with `[project]` and optional `[project.optional-dependencies]`
  for `dev`; a `src/` or package layout with an `__init__.py`; entry points under
  `[project.scripts]`.

## Review checklist

- Typing: a function without annotations, `Any` or `# type: ignore` hiding a real problem,
  `X | None` where `None` is not a real value, a dict where a model exists.
- Exceptions: bare or broad `except`, `contextlib.suppress(Exception)`, an error logged and
  swallowed where the caller needed to know, a failure turned into a default value, a
  re-raise without `from`.
- Resources: an `httpx.AsyncClient`, file, lock or session not closed on every path; a
  session held across an await on an external call.
- asyncio: blocking calls on the loop, an awaited coroutine that was meant to be a task
  (or the reverse), shared state mutated by two coroutines, a task created and never
  awaited or cancelled, `asyncio.sleep` loops instead of events or queues.
- Datetimes: a naive `datetime`, `datetime.now()` without a timezone, a local-time
  comparison, a value serialised without an offset or `Z`.
- Long-running processes: unbounded caches or lists that grow per cycle, documents parsed
  more than once, handles leaked per iteration.
- Paths and subprocesses: paths built from untrusted input without confinement, `shell=True`
  with interpolated strings, a symlink or `..` not rejected where confinement is required,
  zip extraction without a zip-slip guard.
- Dead code, unused imports and parameters, duplicated snippets that should be one function,
  a new helper where one exists.
- Tests: a test that passes if the change is reverted, a test that mocks the unit under
  test or only asserts a mock was called, `@pytest.mark.skip`/`xfail` added, assertions
  loosened (`status_code in (...)`, `assert True`), `time.sleep` papering over a race.

## Testing

- pytest with `asyncio_mode = "auto"` for async tests; fixtures in `conftest.py` for the
  engine (in-memory or temp dir), the client and any patched clock or subprocess.
- Unit tests live where the project puts them (`tests/unit/test_<module>.py` or
  `tests/test_<module>.py`); integration tests that start a real process or hit the network
  are marked (`@pytest.mark.integration` or the project's marker) and skipped in CI.
- Prove behaviour: assert on the outcome (return value, row written, file created, event
  recorded), not on a mock being called. Parametrize boundaries and rejections.
- External HTTP: `httpx.MockTransport` or `respx`, never the real network. Subprocesses:
  a fake executable on `PATH` or a patched `create_subprocess_exec`.
- Coverage report for the gate: `python -m pytest --cov=<package> --cov-report=xml:coverage.xml --cov-report=`,
  then `bin/diff-coverage.sh coverage.xml <base> <min>` (needs `diff-cover`).

## Tooling

- Lint and import order: `ruff check .` (rules E, F, I, N, W, UP, B at least); format with
  `ruff format .` or black if the project chose it. Never add a rule to the ignore list to
  silence a finding.
- Types: `mypy --strict` or the project's config; `pyright` if configured.
- Environment: a virtualenv at `.venv/` with `pip install -e ".[dev]"`; run checks through
  `.venv/bin/<tool>` or `python -m <tool>` so the right interpreter is used.
- Run tests quietly for the fast loop: `python -m pytest -q`; a single file:
  `python -m pytest -q tests/test_x.py`; one test: `-k name`.

## Pitfalls

- A `# noqa` or `# type: ignore` added to make a check pass instead of fixing the cause.
- `except Exception: pass` around network calls "to keep the loop alive"; the loop must
  record the failure and continue deliberately.
- Datetime arithmetic across naive and aware values; countdowns computed from the wrong
  clock.
- Mutable module-level state shared between tests, leaking across the suite.
- A retry loop without backoff or a cap, hammering an external service.
- An `AsyncSession` or DB connection held open across an await on an HTTP client.
- Parsers that assume one shape of input and raise on a slightly different one; they
  should return what they could parse and report what they could not.
- Blocking the loop with large JSON or HTML parsing; move it to a thread.
- `print` left in library code; secrets in log lines or exception messages.
