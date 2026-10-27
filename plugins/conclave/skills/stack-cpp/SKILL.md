---
name: stack-cpp
description: Knowledge pack for standard modern C++ (17, 20, 23) independent of any framework - best practices, strict memory and resource management, conventions, review checklist, testing, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead; pair it with stack-qt6 or stack-qt5 for Qt code.
user-invocable: false
---
# C++ stack pack

Applies to any C++ code: libraries, services, tools, desktop applications. Framework
packs (`stack-qt6`, `stack-qt5`) add their own rules on top; this pack is the floor they
stand on. The standard is the one the build pins (`CMAKE_CXX_STANDARD`); never use a
feature the pinned standard lacks, never leave one unused that would make the code
clearer.

## Idioms

The discipline here is the one taught by the modern C++ best-practices community: let the
compiler and the type system do the checking, make ownership and mutability visible in
the code, and treat every warning as a defect.

- **Const everything.** Variables, parameters, members and member functions are `const`
  unless they must change; `constexpr` for anything computable at compile time;
  `static constexpr` for class constants instead of macros or enums-as-constants.
- **Initialise everything.** Every member has a default member initialiser or is set in
  every constructor's initialiser list, in declaration order; brace-initialisation
  (`T x{...}`) so narrowing is a compile error; no uninitialised locals, ever.
- **No raw `new`/`delete`.** `std::unique_ptr` for sole ownership, `std::shared_ptr` only
  when ownership is really shared, `std::make_unique`/`std::make_shared`; raw pointers
  and references mean "observe, do not own" and never outlive the owner; `std::span` and
  `std::string_view` for non-owning ranges, consumed within the full expression unless
  the referent's lifetime is documented.
- **RAII for every resource.** Files, locks (`std::scoped_lock`, `std::lock_guard`),
  handles, transactions and cursors live in objects whose destructor releases them;
  no `close()` that an early return or an exception can skip; `gsl::finally`-style scope
  guards when there is no type.
- **Rule of zero.** A class owns resources through members that own themselves, so it
  declares none of the five special members; when it must declare one it declares all
  five (`= default` or `= delete` spelled out) and its destructor is `virtual` if anything
  derives from it, or the class is `final`.
- **Prefer values and algorithms.** Return by value (copy elision and moves are free);
  `std::optional<T>` for "maybe a value", `std::expected<T, E>` (or the project's
  equivalent) for "value or error", never `-1`, `nullptr` or an empty string meaning two
  things; `<algorithm>` and ranges over hand-written loops; structured bindings over
  `.first`/`.second`.
- **Strong types.** `enum class` over plain enums and `bool` parameters; a small struct
  with a name over a `std::pair`; `explicit` on every single-argument constructor and on
  conversion operators; no implicit conversions between numeric types of different
  signedness or width (`-Wconversion -Wsign-conversion` are on).
- **Interfaces.** `[[nodiscard]]` on every function whose result it would be a bug to
  ignore (and on types that are results); `noexcept` on moves, swaps and destructors;
  `std::string_view`/`std::span` parameters for read-only input; one job per function;
  no out-parameters where a return type works.
- **Explicit types.** Spell the type out; `auto` only when the initialiser already names
  it (`auto p = std::make_unique<T>()`), for iterators, lambdas and template-dependent
  types. Readable beats clever; no complexity for a speed nobody measured.
- **Errors.** Exceptions for failures the caller cannot reasonably check in advance and
  for constructor failure; `std::expected`/`std::optional` on hot or boundary paths;
  catch by `const&`, catch the narrowest type, never swallow; a function that can throw
  is not `noexcept`; destructors never throw.
- **Headers.** `#pragma once`; include what you use, nothing more; forward declarations
  in headers, includes in sources; no `using namespace` in headers; one class per header
  named after it; `inline`/`constexpr` variables instead of ODR traps.
- **Layout and naming.** Follow the project's `.clang-format` and `.clang-tidy`; match
  the naming convention already in the file; a Doxygen comment on every public class and
  function stating purpose, result and failure cases; a one-line comment at every
  non-obvious decision; comments that stay true.
- **Build.** CMake with targets, not globals: `target_compile_features`,
  `target_compile_options`, `target_link_libraries` with `PRIVATE`/`PUBLIC` deliberately
  chosen; `CMAKE_EXPORT_COMPILE_COMMANDS ON`; dependencies through `find_package` and a
  package manager (vcpkg, Conan, FetchContent pinned to a tag), never vendored copies
  edited in place; warnings as errors in CI.

## Review checklist

- **Undefined behaviour and lifetime:** dangling references, pointers and views (a
  `std::string_view` of a temporary past the full expression, an iterator after
  `insert`/`erase`/reallocation, a reference into a vector that grows); use after move;
  signed overflow; uninitialised reads; out-of-bounds (`operator[]` where `at()` or a
  checked index was needed); `reinterpret_cast` to deserialise; type punning through
  unions; order of destruction between members and between statics; data races on
  anything shared without a lock or an atomic.
- **Ownership:** a raw `new` with no owning type; a raw pointer stored past its owner;
  `shared_ptr` where `unique_ptr` was meant (shared ownership is a design claim);
  `shared_ptr` cycles; `std::move` of a `const` or of something used afterwards; a
  returned reference to a local or to a member of a temporary.
- **Const-correctness and conversions:** `mutable` or a non-const member function where
  `const` belongs; a copy where a `const&` or a move was meant; implicit narrowing;
  signed/unsigned comparison; `int` for sizes and indexes where `std::size_t` or
  `std::ptrdiff_t` is required; `char` arithmetic; `bool` from a pointer or an integer by
  accident.
- **Interfaces:** results that can be ignored but must not be (missing `[[nodiscard]]`);
  error states indistinguishable from valid ones; functions that do two things; a `bool`
  parameter whose meaning is invisible at the call site; macros where a function,
  `constexpr` or a template would do; a public member that should be private.
- **Resources:** an early return or a throw that skips a release; a lock held across a
  call that can block, re-enter or take another lock in a different order; a file or
  socket not closed on every path; a thread not joined or detached deliberately.
- **Exceptions:** one crossing a boundary that cannot handle it (a C callback, a
  destructor, a `noexcept` function, a thread entry); a catch that swallows; a catch by
  value that slices.
- **Modern C++ used where it makes code clearer** (ranges, concepts, `std::format`,
  designated initialisers, `std::optional`/`std::expected`, structured bindings,
  `constexpr`) and NOT used where it only shows off; `auto` hiding a type the reader
  needs; a template where a plain function would do.
- **Correctness for every caller:** a change correct for the reported case and wrong for
  another caller of the same function is the most common defect in a fix; read the
  callers.
- **Duplication and dead code:** a second copy of a helper, an unused parameter, a
  commented-out block, a `#if 0`.
- **Build hygiene:** a warning silenced with a pragma or a flag instead of fixed; a new
  dependency without a reason; `-fpermissive`, `-Wno-error` or a disabled sanitizer.
- **Tests:** a test that passes if the change is reverted; `assert(true)` after a call;
  a sleep as synchronisation; a test that reads private state instead of observable
  behaviour.

## Testing

- Framework: whatever the project already uses (Catch2, GoogleTest, doctest, Boost.Test);
  every test executable registered with `add_test` (or `catch_discover_tests`/
  `gtest_discover_tests`) so `ctest --test-dir build --output-on-failure` runs it.
- One test per behaviour, named after the behaviour; data-driven sections or parametrised
  tests for variants; the success path, each failure path and the boundary between them.
- Prove behaviour through the public interface: return values, exceptions thrown, files
  written, observable state. A test that reaches into private members or asserts on an
  internal call order is a smell.
- Hermetic: temporary directories (`std::filesystem::temp_directory_path` plus a unique
  subdirectory removed at the end), no real network, no fixed sleeps; time and randomness
  injected through an interface so tests control them.
- Sanitizers at least once per change on the touched targets: a separate build directory
  with `-fsanitize=address,undefined` (and `thread` for concurrent code); a clean
  sanitizer run is part of "checks passed" when the project configures one.
- Fuzz the parsers and decoders when the project has a fuzz target (libFuzzer or AFL++);
  a new input format without a fuzz target is a gap to report.
- Coverage: a dedicated build directory with `--coverage` (gcc) or
  `-fprofile-instr-generate -fcoverage-mapping` (clang), run `ctest`, then
  `gcovr --cobertura coverage.xml` or `llvm-cov export -format=lcov` for the diff gate.

## Tooling

- Configure and build: `cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug` then
  `cmake --build build -j`; tests: `ctest --test-dir build --output-on-failure`; a single
  test: `ctest --test-dir build -R '^<name>$'`.
- Warnings: the project's baseline should include `-Wall -Wextra -Wpedantic -Wshadow
  -Wconversion -Wsign-conversion -Wnon-virtual-dtor -Wold-style-cast -Wcast-align
  -Woverloaded-virtual -Wnull-dereference -Wdouble-promotion -Wformat=2
  -Wimplicit-fallthrough` (or `/W4 /permissive-` on MSVC) and `-Werror` in CI. A change
  that adds a warning is not done.
- Static analysis: `clang-tidy -p build <files>` with the project's `.clang-tidy`
  (`bugprone-*`, `cppcoreguidelines-*`, `modernize-*`, `performance-*`, `readability-*`
  are the usual baseline); `cppcheck --project=build/compile_commands.json
  --enable=warning,style,performance`.
- Format: `clang-format -i` per the project's `.clang-format`; never reformat files the
  task did not touch.
- Dependencies: `vcpkg`, Conan or `FetchContent` pinned to a tag or commit; lockfiles or
  manifests change only when the task calls for it.

## Pitfalls

- A `std::string_view` or `std::span` stored in a member, captured by a lambda that
  outlives the call, or returned from a function that built the string locally.
- `push_back` into a vector while holding a reference or iterator into it.
- A `std::move` that leaves an object in a state the next line reads.
- A lambda capturing `this` or a reference, stored in a callback that fires after the
  owner is gone; capture by value or a weak handle, and unregister in the destructor.
- `std::shared_ptr` passed around to avoid thinking about ownership; cycles that never
  free; `shared_from_this()` in a constructor.
- Integer promotion and conversion surprises: `unsigned` arithmetic wrapping, `size_t`
  minus a larger `size_t`, `int` times `int` overflowing before the assignment to
  `int64_t`, a `char` compared with an `int` literal.
- `static` locals and globals with non-trivial constructors whose initialisation order
  across translation units is unspecified.
- A `switch` over an `enum class` without a `default` or with an accidental
  fall-through; `-Wswitch` and `[[fallthrough]]` make both visible.
- Exceptions in destructors, in `noexcept` functions, or escaping a thread.
- A `const char*` or `std::string` built in one thread and read in another without
  synchronisation; "it is just a read" is still a race when there is a writer.
- `-O2` hiding undefined behaviour that `-O0` happened to tolerate; run the sanitizers in
  the configuration the users get.
- A warning fixed by a cast rather than by fixing the type.
- Build directories committed, or sanitizer and coverage builds mixed with the normal one.
