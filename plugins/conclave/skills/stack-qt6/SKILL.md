---
name: stack-qt6
description: Knowledge pack for Qt 6 applications (Widgets and Qt Quick, CMake) - the Qt 6 ecosystem on its own terms: object model, signals and slots, threads and event loops, containers and strings, Qt SQL, the QML/C++ boundary, Qt Test, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead together with stack-cpp.
user-invocable: false
---
# Qt 6 stack pack

Applies to Qt 6.x code (Widgets, Qt Quick/QML, Qt Core services) built with CMake and
tested with Qt Test through `ctest`. Qt is its own ecosystem on top of C++: its object
model, memory rules and threading model replace the standard library's in the places
they cover, and this pack describes those places. The C++ floor (`stack-cpp`) still
applies to everything else. The Qt 6 minor version the project pins decides which APIs
exist; when a claim hinges on Qt behaviour, read the installed Qt headers or sources
rather than memory.

## Idioms

- **Ownership through the object tree.** Every `QObject` has a parent or an owning
  `std::unique_ptr`; a child is deleted with its parent; `QPointer<T>` to observe an
  object someone else may delete; `deleteLater()` from inside a slot or from another
  object, never `delete this`; non-`QObject` resources follow the C++ rules
  (`std::unique_ptr`, RAII). Layouts and views take ownership of what is added to them;
  do not double-own.
- **RAII for Qt resources.** `QMutexLocker`/`QReadLocker`/`QWriteLocker` for locks,
  `QSignalBlocker` for blocking signals, `QFile` opened in a scope that closes it,
  `QSqlDatabase::transaction()` paired with `commit()`/`rollback()` on every path,
  `QScopedValueRollback` for temporary state.
- **Signals and slots.** Pointer-to-member `connect` only (compile-time checked);
  functor connects always with a context object (`connect(sender, &S::sig, receiver,
  [=] {...})`) so the connection dies with the receiver; `Qt::QueuedConnection` across
  threads, `Qt::UniqueConnection` when a connect can run twice; signals carry values, not
  pointers to stack data; `QMetaObject::invokeMethod` with a functor to hop threads.
- **Properties and bindings.** `QProperty`/`QBindable` and `Q_OBJECT_BINDABLE_PROPERTY`
  for bindable state; where a classic `Q_PROPERTY` is used its `NOTIFY` signal fires on
  every change and only on change; derived values are computed, not stored.
- **Threads.** The worker-object pattern (`moveToThread`), never subclass `QThread` for
  work; widgets, `QPixmap`, models and the QML engine touched only from the GUI thread;
  results delivered through signals; `QtConcurrent::run` or `QThreadPool` with
  `QFutureWatcher` or `QFuture::then` for one-off jobs; `QPromise`/`QFuture` for
  producer/consumer with progress and cancellation; cancellation through
  `QFuture::cancel` or an atomic flag checked in the loop.
- **Strings and containers.** `QString` for user-visible and Unicode text, `QByteArray`
  for bytes, `QStringView` and `QLatin1StringView` for non-owning reads consumed within
  the full expression, `QStringLiteral`/`u"..."_s` for constants, `std::string` only at
  library boundaries; `qsizetype` for sizes and indexes; implicit sharing understood
  (copies are cheap, non-const access detaches) and `std::as_const` in range loops;
  `QList` is the vector (`QVector` is an alias), `QHash` when order does not matter,
  `QMap` when it does; `QRegularExpression`, never a hand-rolled parser for a regex job.
- **Model/View.** A `QAbstractItemModel` subclass wraps every structural change in the
  matching `begin*`/`end*` pair, emits `dataChanged` with accurate ranges and roles,
  honours the parent index in `rowCount`/`columnCount`/`index`, keeps roles in an enum
  and exposes `roleNames()` for QML; views never cache model data;
  `QSortFilterProxyModel` over re-sorting by hand.
- **QML/C++ boundary.** Types exposed with `QML_ELEMENT`/`QML_NAMED_ELEMENT` in a
  `qt_add_qml_module` module, not context properties; data handed to QML is a typed
  `Q_GADGET`/`QObject` or a model, never a `QVariantMap`; `Q_INVOKABLE` arguments and
  returns are types QML converts cleanly; required properties declared `required`;
  singletons through `QML_SINGLETON`; QML files pass `qmllint`.
- **Application plumbing.** Resources through `qt_add_resources` or the QML module;
  user-visible strings wrapped in `tr()` with `lupdate`/`lrelease` in the build;
  paths from `QStandardPaths`; settings through `QSettings` with a stable organisation
  and application name; logging through `QLoggingCategory`, not `qDebug()` sprinkled.
- **Headers and build.** `Q_OBJECT` on every class with signals, slots or properties;
  `override` on every overridden virtual; CMake with `qt_standard_project_setup()`,
  `qt_add_executable`/`qt_add_library`, `find_package(Qt6 REQUIRED COMPONENTS ...)`,
  `target_link_libraries(... PRIVATE Qt6::Core ...)`, `CMAKE_AUTOMOC`/`AUTORCC`/`AUTOUIC`
  through the standard setup, `qt_finalize_executable`/deployment through
  `qt_generate_deploy_app_script`.

## Review checklist

- **Object lifetime and thread affinity:** a `QObject` created with `new` and no parent
  or owner; an object owned twice (parent and `unique_ptr`); which thread owns each
  `QObject` and whether `deleteLater()` posts to an event loop that is running;
  `moveToThread` preconditions (no parent, called from the current owner thread); a parent
  in one thread and a child in another; an object destroyed while queued slots or
  deferred deletes targeting it are pending; `sender()` read in a queued slot; a widget,
  pixmap, model or QML engine touched off the GUI thread.
- **Connections:** a string-based `SIGNAL()/SLOT()` connect; a functor connect without a
  context object whose receiver can die first; the connection type chosen for the thread
  pair; argument lifetime across a queued connection (types registered with the meta
  type system, no references to stack data); re-entrancy from a `DirectConnection` into
  the emitter's state; a signal emitted while holding a lock the slot may also take; a
  signal emitted from a half-constructed object or a destructor; a `connect` in a
  constructor that duplicates connections on re-creation.
- **Event loops and pools:** `QThread::sleep`, `waitForFinished` or a blocking wait on
  the GUI thread; `QThreadPool`/`QRunnable` ownership (`autoDelete`); nested event loops
  (`QEventLoop::exec`, modal dialogs, `QCoreApplication::processEvents`) re-entering code
  that is not re-entrant; a `QTimer` started from a thread other than its owner; a worker
  that blocks `quit()` from stopping it.
- **Properties and QML:** a `Q_PROPERTY` without `NOTIFY` or with a signal emitted even
  when the value did not change (binding loops); `Q_INVOKABLE` argument conversions
  (`QVariant` to the declared type, lists and maps); data exposed as a `QVariantMap`;
  context properties that outlive the engine; a type used from QML that is not
  registered in the module; the model contract (begin/end pairs, `dataChanged` ranges,
  `rowCount` honouring the parent, `roleNames()`).
- **Containers and strings:** detachment on non-const access in a loop; iterator
  invalidation across `insert`/`erase`; `int` where `qsizetype` is needed; a `QStringView`
  of a temporary viewed past the full expression; a `QString` built from `const char*`
  by implicit conversion where the encoding matters; `QHash` where order matters;
  `QString::number` instead of `QLocale` for user-visible numbers.
- **Qt SQL:** one `QSqlDatabase` connection per thread (a connection name shared across
  threads is a defect); a `QSqlQuery` outliving the connection it was created on; the
  SQLite driver's deferred `BEGIN` (the transaction starts at the first write, not at
  `transaction()`); a `QSqlDatabase` handle kept across `removeDatabase()` or `close()`;
  `prepare`/`bindValue` instead of string-built SQL; a query result read after the
  connection closed.
- **Exceptions:** one crossing an event handler, a slot, a `QRunnable` or the QML engine
  (Qt is not exception-safe); error reporting through return values,
  `std::optional`/`std::expected` or signals instead.
- **Plumbing:** user-visible strings not wrapped in `tr()`; hardcoded paths; settings
  keys spread across files; a resource referenced by a path that is not in any module;
  QML files that fail `qmllint`; a missing `Q_OBJECT`; a `.cpp` included; a header pulling
  in a widget where a forward declaration would do.
- **Deprecations:** anything `QT_DEPRECATED_SINCE` for the pinned minor version; APIs
  that changed behaviour between the Qt 6 minors the project supports; build flags
  `QT_DISABLE_DEPRECATED_UP_TO` honoured.
- **Tests:** `QVERIFY(true)` after a call; `QTest::qWait` as a synchronisation primitive
  instead of `QSignalSpy::wait` or `QTRY_COMPARE`; a custom model without
  `QAbstractItemModelTester`.

## Testing

- Qt Test: `QTEST_MAIN` for widget tests, `QTEST_GUILESS_MAIN` for non-widget code;
  `qt_add_test`-style targets or `add_test` so `ctest --test-dir build --output-on-failure`
  runs them; one test function per behaviour, data rows (`_data()` with `QTest::addRow`)
  for variants.
- `QSignalSpy` to assert a signal fired with the right arguments; `QTRY_COMPARE` /
  `QTRY_VERIFY` with a bounded timeout for asynchronous outcomes; `QAbstractItemModelTester`
  on every custom model; `QTest::keyClick`/`mouseClick` for widget interaction;
  Qt Quick Test (`QUICK_TEST_MAIN`) for QML components.
- Hermetic: `QTemporaryDir` for files, a scratch `QSettings` file or `QSettings::setPath`
  for settings, `HOME` and the XDG directories pointed at a sandbox when the code reads
  them, `QT_QPA_PLATFORM=offscreen` so GUI tests run headless; never touch the user's
  real configuration or data.
- Prove behaviour through the public interface: emitted signals, model contents, files
  written, properties read back. A test that reaches into private members is a smell.
- Sanitizers at least once per change on the touched targets, in a separate build
  directory with `-fsanitize=address,undefined`.
- Coverage: a dedicated build directory with `--coverage`, run `ctest`, then `gcovr
  --cobertura coverage.xml` (or `llvm-cov`) for the diff gate; QML lines are not
  measured by gcov, so QML behaviour is covered by Qt Quick Test or end-to-end scenarios.

## Tooling

- Configure and build: `cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
  -DCMAKE_PREFIX_PATH=<Qt install>` then `cmake --build build -j`; tests:
  `ctest --test-dir build --output-on-failure`; one test: `ctest --test-dir build -R '^<name>$'`.
- Static analysis: `clang-tidy -p build` (with `QT_ANNOTATE_ACCESS_SPECIFIER` noise
  understood), `clazy` for Qt-specific checks (`clazy-standalone -p build <files>` or
  `-Xclang -plugin-arg-clazy` levels 0 and 1), `qmllint` on every QML file
  (`cmake --build build --target all_qmllint`), `cppcheck` with the compile database.
- Format: `clang-format -i` per the project's `.clang-format`; `qmlformat` for QML; never
  reformat files the task did not touch.
- Qt tools: `lupdate`/`lrelease` for translations; `qt_generate_deploy_app_script`,
  `windeployqt`/`macdeployqt` for packaging; Qt Creator's `.user` files stay out of git.

## Pitfalls

- A functor connected without a receiver; the receiver dies and the functor touches freed
  memory.
- `deleteLater()` on an object whose thread has no running event loop: it is never deleted.
- Long work in a slot freezing the GUI; move it to a worker object or `QtConcurrent`.
- Modifying a container while iterating it with a range-for (detaches or invalidates).
- A `QStringView` or `QLatin1StringView` stored in a member or returned from a function
  that built the string locally.
- A `Q_PROPERTY` without `NOTIFY`, or with the signal emitted from the setter even when
  the value did not change, causing binding loops in QML.
- A `QSqlQuery` created on one thread's connection and executed from another, or a
  transaction assumed open after `transaction()` on SQLite before any write.
- Forgetting `Q_OBJECT`, which silently breaks `qobject_cast`, properties and signal
  lookup; AUTOMOC not seeing a class declared in a `.cpp`.
- A type used from QML that was registered with `qmlRegisterType` in one place and
  declared `QML_ELEMENT` in another, or a QML module not linked into the executable
  (`qt_import_qml_plugins`).
- Exposing a `QVariantMap` or a `QObject*` with raw-pointer ownership to QML, where the
  engine may take ownership (`QJSEngine::ObjectOwnership`) and delete it.
- `QCoreApplication::processEvents` as a fix for a frozen UI; it re-enters everything.
- A `QTimer` or `QSocketNotifier` created in a thread without an event loop.
- Build directories or `CMakeLists.txt.user` committed; sanitizer builds mixed with the
  normal one.
