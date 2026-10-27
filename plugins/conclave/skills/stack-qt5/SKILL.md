---
name: stack-qt5
description: Knowledge pack for legacy Qt 5 applications (5.15 LTS, qmake or CMake) - what still applies from the Qt object model, what Qt 5 lacks or deprecates, and how to keep code forward-compatible with Qt 6 without migrating. Loaded by Conclave devs, challengers, reviewers and the lead together with stack-cpp.
user-invocable: false
---
# Qt 5 stack pack

Applies to projects pinned to Qt 5 (5.15 is the only maintained line) built with qmake
(`.pro`) or CMake and tested with Qt Test. Qt 5 is a legacy target: the goal in a Qt 5
codebase is to keep it correct and forward-compatible, not to backport Qt 6 idioms that
do not exist there. The C++ floor (`stack-cpp`) applies to everything Qt does not cover;
the standard is usually C++14 or C++17 here, so do not use features the pinned standard
lacks. When a claim hinges on Qt behaviour, read the installed Qt 5 headers rather than
memory.

## Idioms

- **Object model, unchanged.** Every `QObject` has a parent or an owning
  `std::unique_ptr`/`QScopedPointer`; `QPointer<T>` to observe; `deleteLater()` from
  slots, never `delete this`; `QMutexLocker`, `QSignalBlocker` and scoped `QFile` for
  RAII; layouts and views own what is added to them.
- **Signals and slots.** Pointer-to-member `connect` with a context object for lambdas
  (available since 5.2; there is no excuse for string-based `SIGNAL()/SLOT()` in code
  that is touched); `Qt::QueuedConnection` across threads; `Qt::UniqueConnection` when a
  connect can run twice.
- **Threads.** Worker-object pattern with `moveToThread`; widgets and models only on the
  GUI thread; `QtConcurrent::run` with `QFutureWatcher` for one-off jobs (no
  `QFuture::then` or `QPromise` in Qt 5: use the watcher's `finished` signal);
  cancellation through an atomic flag.
- **Strings and containers.** `QString`/`QByteArray` as in Qt 6; `QStringLiteral` for
  constants; `QStringView` exists since 5.10 and `QLatin1String` is the ASCII view;
  `qAsConst` (not `std::as_const` if the standard is pre-17) in range loops over Qt
  containers; sizes are `int` in Qt 5 (`qsizetype` does not exist), so guard against
  overflow on large data; `QVector` and `QList` are distinct types with different
  performance characteristics (prefer `QVector` for value types); `QRegularExpression`,
  never `QRegExp`.
- **Model/View, QML boundary.** The same `QAbstractItemModel` contract as Qt 6
  (`begin*`/`end*` pairs, accurate `dataChanged`, parent index honoured, `roleNames()`);
  QML types registered with `qmlRegisterType`/`qmlRegisterSingletonType` from one place
  (`QML_ELEMENT` with `CONFIG += qmltypes` exists only from 5.15); typed
  `Q_GADGET`/`QObject` over `QVariantMap`; `Q_PROPERTY` with `NOTIFY` that fires only on
  change (no `QProperty` bindables in Qt 5).
- **Forward compatibility.** Build with `DEFINES += QT_DISABLE_DEPRECATED_BEFORE=0x050F00`
  (or the CMake equivalent) so deprecated APIs fail to compile; avoid `QStringRef`,
  `QRegExp`, `QLinkedList`, `QVariant::type()`, `QList::toSet`, `QMap::insertMulti`,
  `QTime` as a stopwatch (use `QElapsedTimer`), `qrand` (use `QRandomGenerator`), the
  `QTextCodec` family where `QStringConverter` will replace it; each of these is gone or
  changed in Qt 6.
- **Build.** qmake: `QT += core gui widgets` (and `quick`, `sql`, `testlib` as needed),
  `CONFIG += c++17 warn_on`, `TEMPLATE = subdirs` for app plus tests, `.pro` files that
  list every source and header (no globs); CMake: `find_package(Qt5 REQUIRED COMPONENTS
  ...)`, `target_link_libraries(... Qt5::Core ...)`, `CMAKE_AUTOMOC`/`AUTORCC`/`AUTOUIC`
  set explicitly (there is no `qt_standard_project_setup` in Qt 5).

## Review checklist

- Everything in the Qt object model that Qt 6 also checks: a `QObject` with no owner,
  double ownership, `deleteLater()` without a running event loop, `moveToThread`
  preconditions, objects destroyed with queued slots pending, a widget or model touched
  off the GUI thread, a functor connect without a context object, string-based connects,
  wrong connection type for the thread pair, re-entrancy from `DirectConnection`, a signal
  under a lock, nested event loops, `QThreadPool`/`QRunnable` ownership.
- `int`-sized containers: a size or index computed from file or network data that can
  exceed `INT_MAX`; `QByteArray` building a buffer over 2 GB.
- `QList<T>` of a large or non-movable `T` where `QVector<T>` was meant (Qt 5 `QList`
  heap-allocates such elements); `QLinkedList` anywhere.
- A deprecated API used in touched code when the project enables
  `QT_DISABLE_DEPRECATED_BEFORE`; `QRegExp` for new regex work; `QStringRef` in new code.
- A `.pro` file that misses a new source or header (silent link or moc failure); a
  resource not listed in a `.qrc`; `Q_OBJECT` missing; `CONFIG += qmltypes` claims without
  the 5.15 minimum.
- Qt SQL: the same per-thread connection rule, `QSqlQuery` lifetime relative to its
  connection, SQLite deferred `BEGIN`, and `prepare`/`bindValue` over string-built SQL.
- QML: `qmlRegisterType` calls spread across files or duplicated; a context property
  that outlives the engine; `QVariantMap` handed to QML; a `Q_PROPERTY` without
  `NOTIFY`.
- Migration debt added rather than removed: new code that would not compile against
  Qt 6 when a Qt 6-compatible spelling exists at no cost.
- Tests: `QTest::qWait` as synchronisation instead of `QSignalSpy::wait`/`QTRY_*`;
  `QVERIFY(true)` after a call; no `QAbstractItemModelTester` (available since 5.11) on a
  custom model.

## Testing

- Qt Test with `QTEST_MAIN`/`QTEST_GUILESS_MAIN`; each test is a target (qmake
  `TEMPLATE = app` with `QT += testlib` and `CONFIG += testcase`, or CMake `add_test`) so
  `make check` or `ctest --output-on-failure` runs it.
- `QSignalSpy`, `QTRY_COMPARE`/`QTRY_VERIFY` with bounded timeouts,
  `QAbstractItemModelTester`, data-driven test functions with `_data()`.
- Hermetic: `QTemporaryDir`, scratch `QSettings`, `QT_QPA_PLATFORM=offscreen`, sandboxed
  `HOME`/XDG directories when the code reads them.
- Sanitizers in a separate build (`CONFIG += sanitizer sanitize_address sanitize_undefined`
  in qmake, or the CMake flags); coverage with `--coverage` (`QMAKE_CXXFLAGS +=
  --coverage` and `QMAKE_LFLAGS += --coverage`) then `gcovr --cobertura coverage.xml`.

## Tooling

- qmake: `qmake <project>.pro && make -j`; tests: `make check` or run the test binaries
  from the subdirs; out-of-source builds in a `build/` directory kept out of git.
- CMake: `cmake -S . -B build -DCMAKE_PREFIX_PATH=<Qt5 install>` then
  `cmake --build build -j`; `ctest --test-dir build --output-on-failure`.
- Static analysis: `clang-tidy -p build` (needs a compile database: for qmake projects
  use `bear -- make` or `compiledb`), `clazy` with the `qt5` checks, `cppcheck`.
- Format: `clang-format -i` per the project's `.clang-format`; never reformat files the
  task did not touch.
- Qt tools: `lupdate`/`lrelease`; `linuxdeployqt`/`windeployqt`/`macdeployqt`.

## Pitfalls

- A functor connected without a receiver that outlives it; the same class of bug as in
  Qt 6, and the most common one.
- `int` overflow in sizes and offsets on large files or datasets.
- `QList` of a large struct causing a heap allocation per element.
- A `QRegExp` kept for "compatibility" in new code; it is gone in Qt 6.
- `QTime::elapsed()` as a timer, broken across midnight; `QElapsedTimer` instead.
- A `.pro` file edited for one source but not the header (moc not run) or a `.qrc` not
  regenerated after a resource was added.
- `qmlRegisterType` called twice for the same type and URI from two translation units.
- Qt Creator `.pro.user` and `CMakeLists.txt.user` files committed.
- A fix that uses a Qt 6-only API (`QStringView` methods added in 6.x, `QFuture::then`,
  `qsizetype`) and does not compile against the pinned Qt 5.
