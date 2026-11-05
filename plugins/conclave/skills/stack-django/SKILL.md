---
name: stack-django
description: Knowledge pack for Django 5.2 LTS and 6.x with the ORM, migrations, forms, templates, the admin, optional Django REST Framework, async views and background tasks: idioms, review checklist, testing, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead.
user-invocable: false
---
# Django stack pack

Load together with `stack-python`. Covers Django 5.2 LTS and 6.x: models and the ORM,
migrations, views and URLs, forms and templates, the admin, authentication and
permissions, async views, background work (Celery or the `django.tasks` framework in
6.0+), and Django REST Framework (DRF) where the project uses it.

## Idioms

- Layering: a view (function or class-based) validates input through a form or a
  serializer, calls a service or a model method and returns a response; business rules in
  services, model methods or custom `QuerySet` methods exposed with `as_manager()`; no
  logic in templates, and signals only for cross-app hooks the caller cannot know about.
- Models: every `ForeignKey` with an explicit `on_delete` and `related_name`;
  `Meta.constraints` (`UniqueConstraint`, `CheckConstraint(condition=Q(...), name=...)`;
  the old `check=` keyword is gone in 6.0) instead of `unique_together` and ad-hoc validation; closed string sets as `TextChoices`/`IntegerChoices`; `__str__`
  defined; a `default` that is a callable (`default=dict`, `default=timezone.now`), never
  the result of calling one; user references through `settings.AUTH_USER_MODEL` and
  `get_user_model()`, never an imported `User`.
- Queries: `select_related` and `prefetch_related` for every relation touched in a loop;
  `exists()` rather than `count()` or truthiness for presence; `update()`,
  `bulk_create` and `bulk_update` for sets; `F()` for read-modify-write of a counter;
  aggregation in the database; `iterator(chunk_size=...)` for large scans;
  `transaction.atomic()` around multi-row writes with `select_for_update()` when a row is
  read and then written.
- Side effects that depend on a write (email, enqueueing a task, a webhook) are scheduled
  with `transaction.on_commit`, never run inside the transaction.
- Migrations: one generated migration per model change, read before it is committed;
  data migrations as a separate `RunPython` with a `reverse_code`, using
  `apps.get_model`, never an imported model; a migration applied on the base branch is
  never edited; new columns on populated tables nullable or with a default (`db_default`
  when the database should own it); on PostgreSQL large indexes through
  `AddIndexConcurrently` in a migration with `atomic = False`.
- Settings: `SECRET_KEY`, the database password and every other secret from the
  environment; `DEBUG` defaults to off; `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
  explicit; the `SECURE_*`, `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` settings on
  in production; `USE_TZ = True` and `timezone.now()` everywhere; file storage through
  the `STORAGES` setting.
- Forms and serializers: an explicit `fields` list, never `fields = "__all__"`; server-set
  values (`owner`, timestamps, status) in `read_only_fields` or set in the view, not
  accepted from the client; field validation in `clean_<field>`/`validate_<field>`, cross-
  field rules in `clean()`/`validate()`; one error shape for the whole API.
- URLs named and reversed (`reverse()`, `{% url %}`), grouped under an app namespace; path
  converters instead of regexes where they fit.
- Templates: autoescaping on; `format_html` for markup built from values; `mark_safe` and
  `|safe` only on content the server built from trusted parts; `{% csrf_token %}` in every
  POST form.
- Authentication and authorisation: `LoginRequiredMixin`/`@login_required` (or the
  `LoginRequiredMiddleware`, 5.1+) on every view that is not public; permissions checked
  with `has_perm` or a `PermissionRequiredMixin`; object access always filtered by the
  requesting user (`Model.objects.filter(owner=request.user)`), never fetched by id and
  checked afterwards; passwords only through `set_password`/`check_password`.
- Async views only when they await something; ORM access from them through the `a*`
  methods (`aget`, `acreate`, `asave`, `aiterator`) or `sync_to_async`; a blocking call in
  an async view is a defect.
- Background work: tasks idempotent, given ids rather than instances, enqueued on commit;
  Celery with `acks_late` and a time limit per task, or `django.tasks` (6.0+) with the
  backend chosen per environment.
- Uploads: `FileField(upload_to=<callable>)` naming the file server-side, type and size
  validated in the form or serializer, media served by the web server, never by Django.
- Admin: `list_select_related`, `autocomplete_fields` or `raw_id_fields` on large
  relations, `readonly_fields` for server-set values, actions that touch many rows
  confirmed first.

## Review checklist

- N+1 and query cost: a relation read inside a loop or a template without
  `select_related`/`prefetch_related`; `len(qs)` or `if qs:` for presence; a per-object
  `save()` where `update()` or `bulk_update` applies; a `SerializerMethodField` or a model
  property that queries per object; a list endpoint without pagination or a cap.
- Migrations: a model change without a migration; a migration edited after it was applied
  on the base; `RunPython` without `reverse_code` or importing a model; a non-nullable
  column with no default on a populated table; a merge migration nobody read; an index on
  a large PostgreSQL table added inside a transaction.
- Transactions: a read then a write without `select_for_update()` inside `atomic()`;
  `select_for_update()` outside a transaction; a side effect inside `atomic()` that is not
  deferred with `on_commit`; `update()`, `bulk_create` or `bulk_update` used where an overridden `save()` or a
  `pre_save`/`post_save` receiver held required logic (they bypass both); `QuerySet.delete()`
  where an overridden `Model.delete()` held it (the delete signals still fire).
- Input: `fields = "__all__"` or an `exclude` that lets a client set a server-owned field;
  `.raw()`, `.extra()` or `cursor.execute` with interpolated values; request parameters
  passed into `filter(**kwargs)`, `order_by` or `values()` without a whitelist; a redirect
  to a `next` parameter not checked with `url_has_allowed_host_and_scheme`; an upload
  without a size and type cap; `mark_safe`, `|safe` or `{% autoescape off %}` near user
  content.
- Access control: a view without the login or permission check its neighbours have; an
  object fetched by id without filtering on the owner; `is_staff` where `has_perm` was
  meant; `@csrf_exempt` added; a DRF view relaxing `permission_classes` or
  `authentication_classes`; a password or token compared with `==`.
- Settings: `DEBUG = True` reachable in production; a secret with a literal fallback;
  `ALLOWED_HOSTS = ["*"]`; `CORS_ALLOW_ALL_ORIGINS`; cookie and HSTS settings off;
  `SECURE_PROXY_SSL_HEADER` missing behind a proxy; middleware order changed.
- Responses: `.get()` without `get_object_or_404` or a handled `DoesNotExist` (a 500 for a
  missing row); a wrong status for the outcome; an exception message carrying a secret or a path into the response.
- Async: a synchronous ORM call in an async view (`SynchronousOnlyOperation`); an async
  view awaiting a blocking client; `sync_to_async(..., thread_sensitive=False)` around code that is not
  thread-safe; `transaction.atomic()` used from async code.
- Signals: business logic or an external call in `post_save`; a receiver connected at
  import time without `dispatch_uid`; a receiver not registered in `AppConfig.ready()`.
- Datetimes: `datetime.now()` or `date.today()` with `USE_TZ`; a naive value compared with
  a database value; `auto_now_add` where the value must be settable.
- Dead code: an app in `INSTALLED_APPS` nothing uses, a URL with no view, a template no
  view renders, a setting nothing reads, a migration that only reorders fields.
- Tests: `django_db` without `transaction=True` where row locking across connections is
  under test; `transaction=True` where `django_capture_on_commit_callbacks` would do; a
  settings-dependent test without `override_settings`; a JSON fixture where a factory exists; a test that hits the network
  or writes outside `MEDIA_ROOT` under `tmp_path`.

## Testing

- pytest with `pytest-django` (`DJANGO_SETTINGS_MODULE` under
  `[tool.pytest.ini_options]`), `@pytest.mark.django_db` per test or module,
  `transaction=True` only where the behaviour needs it (locking across connections,
  `TransactionTestCase` semantics); or `django.test.TestCase` and `manage.py test` when the
  project chose it. Follow the project's choice; do not mix.
- Clients: the `client` fixture or `django.test.Client`, `client.force_login(user)`;
  DRF's `APIClient` with `force_authenticate`; `RequestFactory` for a view in isolation;
  `Client(enforce_csrf_checks=True)` for the test that proves CSRF is enforced.
- Data from factories (`factory_boy` or `model_bakery`), not JSON fixtures; one factory per
  model in the project's `factories` module; `Faker` seeded.
- Prove the outcome: the row (`Model.objects.get(...)`), the status and body, the redirect
  (`assertRedirects`), the template (`assertTemplateUsed`), the form error
  (`form.errors`), the email in `mail.outbox`, the enqueued task (Celery
  `task_always_eager` or the tasks backend's immediate backend), the deferred callbacks
  (`django_capture_on_commit_callbacks(execute=True)` or
  `TestCase.captureOnCommitCallbacks`).
- Every expected failure from the brief as a test: 403 for the wrong owner, 404 for a
  missing row, 400 or 422 with the field error for each rejected input, 405 for a wrong
  method, 429 when throttled, CSRF rejected.
- Query budgets: `django_assert_num_queries` or `assertNumQueries` on list views and
  serializers, so an N+1 fix cannot regress silently.
- Migrations: `python manage.py makemigrations --check` as a check; a data migration gets a
  test that builds the previous state with `MigrationExecutor` (or `django-test-migrations`)
  and runs the migration forward and back.
- Time through `time-machine` or `freezegun`, never `sleep`; settings through
  `override_settings` or the `settings` fixture; `MEDIA_ROOT` pointed at `tmp_path`.
- Coverage for the gate as in the Python pack; on a `manage.py test` project,
  `coverage run manage.py test` then `coverage xml`.

## Tooling

- `python manage.py check --deploy` against the production settings; `makemigrations
  --check`; `migrate`; `showmigrations`; `sqlmigrate <app> <number>` to read the SQL a
  migration will run before it runs; `python -Wa manage.py test` to surface deprecations.
- Dev server `python manage.py runserver`; production under `gunicorn <project>.wsgi` or
  `uvicorn <project>.asgi:application` for async; `collectstatic` at build time.
- Lint: `ruff check .` with the `DJ` rules enabled next to the project's set; format with
  `ruff format .`. Types: `mypy` with `django-stubs` (`plugins = ["mypy_django_plugin.main"]` under
  `[tool.mypy]` and `[tool.django-stubs] django_settings_module = "..."`), plus
  `djangorestframework-stubs` and `mypy_drf_plugin.main` when DRF is present.
- Query inspection in development: `django-debug-toolbar` and `QuerySet.explain()`;
  `django-extensions` for `shell_plus` and `show_urls`.
- Fast loop: `python -m pytest -q --reuse-db`; `--create-db` after a migration changes the
  schema; one file or `-k name` as in the Python pack.

## Pitfalls

- `default=timezone.now()` or `default={}`: evaluated once at import, shared by every row.
- Logic in an overridden `save()` or a save signal that `update()`, `bulk_create` and
  `bulk_update` silently skip, or in an overridden `delete()` that `QuerySet.delete()`
  skips; `update()` and `bulk_update` also skip `auto_now`.
- A task enqueued inside `atomic()` runs before the row is committed and finds nothing;
  `transaction.on_commit` is the fix, not a retry.
- `qs.filter(a).filter(b)` on a multi-valued relation matches a different set than
  `qs.filter(a, b)`.
- A queryset queried twice: `count()` then iteration, `qs[0]` on an unevaluated
  queryset inside a loop, or `Model.objects.filter(...)` rebuilt per iteration; and the
  reverse, an evaluated queryset reused after a write and serving its cached rows.
- `Model.objects.get()` in a view without `get_object_or_404`: a 500 for a missing row.
- `fields = "__all__"` on a `ModelForm` or `ModelSerializer` turns a later model field
  into a mass-assignment hole.
- Nested writes on a `ModelSerializer` are not supported by default; a `create()` that
  pretends they are drops the nested data.
- `# type: ignore` on `Model.objects` instead of letting `django-stubs` type the manager.
- Serving media or static files through Django in production because it worked with
  `DEBUG = True`.
- Running `migrate` by hand against a shared database, or resolving a conflict with
  `makemigrations --merge` without reading the result.
- `request.user` read in a middleware placed before `AuthenticationMiddleware`.
- `transaction.atomic()` in an async view: not supported. Put the atomic block in a sync
  function and call it through `sync_to_async`.
- `TransactionTestCase` or `transaction=True` on every test because one needed it; the
  suite slows by an order of magnitude.
