# CHANGELOG — vs IMPLEMENTATION_SPEC_Phase0_Phase1.md

## Phase 0 — Foundation (complete)

Built per spec §3/§4 exactly: repo structure, base mixins (`PKMixin`, `TenantMixin`,
`TimestampMixin`, `SoftDeleteMixin`, `ProvenanceMixin`), `tenants`/`users` models,
JWT auth (argon2 password hashing), Postgres RLS with `app_user` as a forced,
non-superuser role, append-only `audit_log` via SQLAlchemy mapper events,
`/health` + `/health/db`, structured logging with request/tenant id context.

### Decisions made where the spec was silent (not guessed — reasoned from the
spec's own constraints, listed here for review)

1. **`POST /auth/register` semantics** — spec lists the route but not its
   payload. Confirmed with user: creates a new `Tenant` + first `admin` `User`
   in one transaction (self-serve college signup), returning tokens
   immediately. *(User-confirmed, not inferred.)*

2. **`POST /auth/login` requires `tenant_slug`** — forced by the spec's own
   `UNIQUE (tenant_id, email)` constraint on `users` (§4.2): the same email can
   exist under different tenants, so email alone can't identify an account.
   Login payload is `{tenant_slug, email, password}`.

3. **RLS bootstrap ordering for login/register** — `tenants` has no
   `tenant_id` column, so it carries no RLS policy (§4.3 only applies RLS to
   tables that have one) and is always readable. Login/register resolve the
   tenant by slug first (no RLS involved), then call `set_tenant_context`
   before touching `users`, avoiding the chicken-and-egg problem of needing a
   tenant context to find the tenant.

4. **Two DB connection strings** — `DATABASE_URL` (app, `app_user`, RLS-bound)
   and `MIGRATIONS_DATABASE_URL` (privileged/owner role for DDL: `CREATE ROLE`,
   `GRANT`, `ENABLE/FORCE ROW LEVEL SECURITY`, `CREATE POLICY`). Forced by
   "non-superuser app role" + migrations needing to create that role and its
   grants. `MIGRATIONS_DATABASE_URL` falls back to `DATABASE_URL` if unset.

5. **`APP_DB_PASSWORD` env var** — the bootstrap migration creates/repasswords
   the `app_user` role from this env var (never hardcoded in the migration
   file), satisfying §4.5 ("secrets via env, never hardcode") while still
   keeping role provisioning as code (Alembic-managed, repeatable).

6. **Audit hooks wired to `users` now, reused unchanged for canonical tables in
   Phase 1** — §4.4 says "implement via SQLAlchemy event hooks... on canonical
   tables," but canonical tables don't exist until Phase 1, while the Phase 0
   DoD (§4.6) requires "audit log writes on canonical insert/update" to be
   demonstrated. `core/audit.py::register_audit_hooks(mapped_class)` is a
   generic, reusable mapper-event registrar; it's applied to `User` (the only
   mutable tenant-owned table in Phase 0) to prove the mechanism now. The same
   function will be called for `Student`, `Attendance`, etc. in Phase 1 with no
   changes to `core/audit.py` itself.
   - **Caveat proven in tests**: the hook is a SQLAlchemy *mapper* event — it
     only fires on ORM-mediated writes (`session.add()` + flush), which is how
     every service in this codebase writes data. Raw SQL `INSERT`s would not be
     audited; none of the app code does that.

7. **`EmailStr` avoided** — would have pulled in `email-validator`, a
   dependency not in the approved list (spec rule 2: confirm deps before
   adding). Used a plain regex-validated `str` instead.

### Acceptance tests passing (§9, Phase-0-relevant subset)

- §9.4 tenant isolation: zero rows with no `app.current_tenant` set; tenant A's
  context can never see tenant B's rows — verified both via raw `psql` against
  the dev container and via `tests/test_rls_isolation.py` (testcontainers).
- Audit log: ORM insert on `User` produces an `audit_log` row with the correct
  `action`/`new_value`; `app_user` cannot `UPDATE` `audit_log` (Postgres grants
  enforce append-only, not just app-level convention).
- Phase 0 DoD: deployed locally, `/health` and `/health/db` green, migrations
  run clean (`alembic upgrade head` from empty DB), login issues a JWT,
  `pytest` suite (9 tests) green.

## Phase 1 — Ingestion pipeline (complete)

Built the full RAW → STAGING → CANONICAL medallion pipeline (spec §5): CSV/
Excel connector, column mapping (+ fuzzy suggest), normalizers/validators,
student entity resolution (deterministic → fuzzy → manual review), idempotent
canonical upserts with provenance, source-precedence conflict detection,
anomaly/completeness reconciliation, and the `sources`/`mappings`/`imports`/
`students` API surface (§7).

### Scope decision: which entity types the pipeline actually loads

The spec requires DDL for all of §6's canonical tables (including `faculty`
and `semester_results`), but the 40-Day Plan scopes Phase 1's *data* to
"attendance + marks + fees" on top of students. Built both model layers, but
the ingestion connector only has entity_type handling for: `student`,
`department`, `programme`, `course`, `enrollment`, `attendance`,
`internal_mark`, `fee`. `faculty` and `semester_results` get tables (so
nothing blocks building them out later) but no connector path yet — same
treatment as the explicit `hostel`/`placement`/`research_publication` stubs.
Flagging this for redirection if faculty/semester-result ingestion is wanted
sooner.

### Decisions made where the spec was silent

1. **Raw file storage: Postgres bytea behind a `StorageBackend` interface**
   (user-directed, not inferred). `raw_files.content BYTEA` holds the bytes
   now; `storage_uri` is kept as the portable pointer so a future
   `S3StorageBackend` is a pure addition — `core/storage.py`'s `save()`/
   `load()` contract doesn't change. Forced a related fix: `raw_files` is
   granted `SELECT, INSERT` only (append-only, §5.2), so `RawFile.id` is
   pre-generated client-side (not left to the server default) — otherwise
   `storage.save()` would need a second `UPDATE` after the initial insert,
   which the grant deliberately disallows.

2. **`rapidfuzz==3.10.1`** (user-approved) for the §5.5 fuzzy name/dob match
   and the §5.3 "suggest mapping" fuzzy header matcher — one library, two
   uses.

3. **Fuzzy-match thresholds are tunable defaults, not spec-given values** —
   §5.5 says "high confidence (≥ threshold)" without naming the threshold.
   Used `HIGH_CONFIDENCE = 90`, `MEDIUM_CONFIDENCE = 70` on a weighted score
   (`0.5×name + 0.4×dob + 0.1×contact`), in `resolution/resolver.py`. Easy to
   make tenant-configurable later; not done now since nothing asked for it.

4. **Source-precedence policy treats same-source re-imports as updates, not
   conflicts** — discovered by manual testing, not designed upfront. §5.7's
   policy ("equal precedence + different value → conflict") read literally
   would flag a corrected re-upload from the *same* source system as
   conflicting with its own prior import, since both share one precedence
   value. Fixed in `reconciliation/conflicts.py::apply_field_with_precedence`:
   when `existing_source_id == incoming_source_id`, the incoming value always
   wins (a source superseding its own earlier extract). The conflict path now
   only fires for genuinely *different* sources at equal precedence —
   verified both ways via manual testing and `test_conflict_handling_*`.

5. **Natural-key upserts are application-level check-then-insert/update, not
   literal SQL `ON CONFLICT`** — spec §5.6 names `ON CONFLICT DO UPDATE`, but
   the per-field conflict-precedence policy (§5.7) needs the *existing* value
   in hand to decide whether to apply an incoming one, which a plain
   `ON CONFLICT DO UPDATE SET x = excluded.x` can't express conditionally.
   Idempotency is preserved (re-running finds the same row by its natural key
   and updates it in place, never duplicates) — just implemented at the ORM
   layer under the caller's transaction instead of as a single SQL statement.

6. **Unresolved cross-entity references quarantine the row, never
   auto-create a placeholder parent** — e.g. an `attendance` row whose
   `roll_no` doesn't match any existing student. Spec doesn't say which way to
   fall on this; auto-creating a bare `Student(name=None, ...)` to satisfy a
   foreign key would pollute the SoT far worse than quarantining the row with
   a clear reason (`UnresolvedReferenceError` → `staging_records.
   validation_status = 'quarantined'`), consistent with "never drop a bad
   row" + "no silent inconsistency."

7. **`import_batches.reconciliation_report JSONB`** — added a column not in
   spec §5.2's list. §5.8 explicitly requires the DQ report to be
   "persist[ed] + expose[d] via imports.py"; §5.2 predates that requirement.
   Closes the gap rather than computing the report on the fly each request.

8. **`semester_results` schema is a minimal invention** — spec names the
   table in §5.6's list but never gives it columns anywhere (unlike every
   other canonical table). DDL only, not wired into ingestion (see scope
   decision above).

9. **Two real bugs caught by testing, not by review**:
   - `actor_user_id_ctx`/`tenant_id_ctx` `ContextVar.reset()` after `yield` in
     a sync FastAPI dependency can raise `ValueError: ... created in a
     different Context` — sync generator dependencies can run their pre- and
     post-yield halves in different worker threads. Fixed by not resetting
     (these are log/audit-only contextvars; a stale value between requests on
     a reused thread is cosmetic, not a correctness issue).
   - `run_pipeline` (a `BackgroundTask`) must never let an exception escape:
     Starlette sends the response body *before* awaiting background tasks, so
     a re-raised exception there crashes the ASGI cycle after the client
     already has a response. Failures are logged + persisted to
     `import_batches.error`/`status=FAILED` instead of re-raised. Test
     helper note: the upload response's JSON is fixed at "RECEIVED" — tests
     must `GET /imports/{id}` afterward to see post-pipeline state, since
     TestClient blocks until the background task finishes but the response
     body was serialized before it ran.

### Acceptance tests passing (§9, all eight)

All eight written in `tests/test_ingestion_pipeline.py`, plus focused unit
tests for the resolver's three confidence bands (`test_resolver.py`) and the
normalizers (`test_normalizers.py`). 34/34 passing. Also manually verified
end-to-end against the local Docker Postgres: messy-CSV upload → quarantine →
canonical load → Student 360 read → idempotent re-import → cross-source
conflict, all behaving as designed.

---

# CHANGELOG — vs IMPLEMENTATION_SPEC_Phase2_StudentSuccessEngine.md

## Phase 2 — Student Success Engine (complete)

Built per spec exactly, in the §12 build order: `risk_configs` /
`risk_assessments` / `risk_findings` / `interventions` /
`intervention_outcomes` / `risk_alerts` / `faculty_scopes` models + one
Alembic migration (RLS + grants on all seven, audit hooks on the five
mutable/security-relevant ones); config seeding; bulk attendance/academic/fee
signal computation; the five rules + scoring/tiering + `RulesRiskEvaluator`
behind the `RiskEvaluator` seam; the recompute engine
(`recompute_for_students`/`_for_tenant`/`_for_import_batch`) with bulk signal
reads, per-student savepoint isolation, and idempotent persist; DPDP minor-
status computation + the parent_contact consent gate; the one-line pipeline
hook; intervention lifecycle + alert generation services; faculty-scope
resolution; and the full `/risk` API surface with tenant + role scoping.

### Decisions made where the spec was silent (reasoned, not guessed)

1. **`PRIVILEGED_ROLES` = `("admin", "principal", "registrar", "iqac")`** —
   spec §13 names the full-visibility group as "admin/principal/registrar/
   management," but Phase 0's `VALID_ROLES` (locked) has no `management`
   role. Read as "every role besides faculty and student," i.e. everything
   else Phase 0/1 already defined. `services/risk/scoping.py`.

2. **`faculty_scopes.scope_type = 'section'` treated as a synonym for course
   code** — the locked Phase 1 schema has no distinct "section" column on
   `enrollment`/`courses`, so both `course` and `section` scope types resolve
   against `Course.code`. `services/risk/scoping.py`.

3. **`internal_marks` ordering key is `(created_at, id)`** — spec §5.2 says
   "order internal_marks by a stable key (term/assessment order)," but the
   locked `internal_marks` schema (Phase 1) has no term/sequence column at
   all. `created_at` is the only deterministic ordering key the table
   actually provides. `services/risk/signals/academic.py`.

4. **Fee "unpaid/partially-paid"** = `amount_paid is None or amount_paid <
   amount_due` — Phase 1's `fees.status` is free-text, not a relied-upon
   enum, so eligibility is read off the numeric columns directly.
   `services/risk/signals/fees.py`.

5. **Attendance trend windows (`attendance_recent_pct`/`_prior_pct`) require
   a *full* `2 × attendance_trend_window` sessions before computing either** —
   spec names the windows but not what happens with a partial history. A
   partial window isn't "the window" the config asked for, so both stay
   `None` rather than risk a sampling artifact — same confidence-guard spirit
   as `ATTENDANCE_BELOW_THRESHOLD`'s `attendance_min_sessions` check (spec
   §6.3's own note). `services/risk/signals/attendance.py`.

6. **Material alert transitions include `('low', 'high')`** in addition to
   spec §11's two named cases (`None -> high`, `watch -> high`) — a prior
   tier of `low` jumping straight to `high` (e.g. several findings appearing
   between two imports) is the same "newly entering high" event in substance.
   `services/risk/alerts.py`.

7. **`GET /risk/students` excludes `tier == 'low'` by default** when no
   `tier` filter is given — spec names the endpoint an "at-risk list," but
   every active student gets an assessment (even a zero-finding one), so an
   unfiltered query would otherwise return the entire student body, not "who
   is at risk." An explicit `tier=low` still returns them.
   `app/repositories/risk_repository.py`.

8. **`interventions.guardian_consent_confirmed_by`** — added a column not in
   spec §4.4's list. §9 requires recording *who* confirmed guardian consent
   for a minor's `parent_contact` intervention; §4.4 predates that
   requirement, same shape of gap as Phase 1's `reconciliation_report`
   addition.

9. **§7's stated invariant `findings == [] ⟺ tier == 'low'`** doesn't hold in
   the *reverse* direction for the named default config: a lone
   `FEE_OVERDUE` finding (weight 15, severity `low`) scores 15, which is
   below the default `watch` cutoff of 25, so it tiers `'low'` while a
   finding is present. Scoring is implemented exactly as specified ("clamped
   sum of weights") and tiering exactly as specified ("score vs threshold"),
   so this is a property of the named default numbers, not a defect in
   `scoring.py`. The forward direction (`findings == [] => score == 0 and
   tier == 'low'`, §15.3's literal acceptance wording) always holds and is
   what's tested. See `tests/test_risk_scoring.py`'s module docstring.

10. **`scoping.py`'s core resolution helpers were written ahead of the §12
    build order** (listed as step 9, but needed by step 8's alert recipient
    resolution) — built once, reused by both; no functional difference from
    building it twice.

### A real bug found and fixed in Phase 0/1 shared infrastructure

`app/api/deps.py::get_tenant_session` sets `actor_user_id_ctx` (a
`contextvars.ContextVar`) in its pre-`yield` half so that
`core/audit.py`'s mapper-event hooks can attribute a write to the
requesting user. **This never actually worked for a write made directly in
a route handler body** (as opposed to a `BackgroundTask` like the ingestion
pipeline): FastAPI/Starlette dispatch a sync generator dependency's
pre-yield half and the route handler itself as *separate*
`run_in_threadpool` calls, each copying a fresh `contextvars.Context` from
the parent async context. A `.set()` made inside the dependency's copied
context does not propagate forward into the handler's own copied context —
confirmed empirically (same `Session` object, same eventual OS thread index,
`actor_user_id` still came back `None` at flush time). Phase 0/1 never
caught this because their only audited table (`users`) is only written via
`POST /auth/register` (no "prior actor" to attribute anyway) and every other
audited write goes through the ingestion pipeline's `BackgroundTask`, which
sets the contextvar once at the very top of one continuous, non-threadpool-
hopping call chain — sidestepping the bug entirely.

Phase 2's audited direct-write endpoints (`PUT /risk/config`, `POST
/risk/interventions`, `PATCH /risk/interventions/{id}`, `POST
/risk/interventions/{id}/outcome`) hit this path squarely, and acceptance
test §15.14 requires correct actor attribution. Fixed at the root rather
than worked around per-route:

- `core/audit.py::_resolve_actor_user_id` now prefers
  `object_session(target).info["actor_user_id"]` — a plain dict on the
  `Session` *instance*, immune to the threadpool-context-copy problem — and
  only falls back to the contextvar for callers that never attach it (the
  ingestion pipeline, where the contextvar still works correctly).
- `get_tenant_session` now also stamps `session.info["actor_user_id"]`
  alongside the (now mostly vestigial, kept for logging) contextvar `.set()`.

This is a change outside the files named in spec §3/§17 (`core/audit.py`,
`api/deps.py`), beyond the promised "one-line pipeline hook + audit-hook
registrations." Justified as a correctness fix to existing, reused
infrastructure that Phase 2's own hard acceptance criteria require — not a
refactor or a new feature. All 81 pre-existing Phase 0/1 tests still pass
unchanged after the fix.

### Acceptance tests passing (§15, all fourteen)

`tests/test_risk_rules.py` (15), `test_risk_scoring.py` (5),
`test_risk_signals.py` (6), `test_risk_engine.py` (7, including the
determinism, idempotency, recompute-on-import, error-isolation, config-
effect, and no-N+1 query-count tests), `test_risk_minor_handling.py` (7),
`test_risk_interventions.py` (3), `test_risk_api.py` (8) — 51 new tests, all
passing. Full suite (Phase 0 + 1 + 2): **89/89 passing**,
`test_rls_coverage.py` green with `EXEMPT_TABLES` empty across all 31
tenant-scoped tables.

### Confirmations

- **No new dependencies.** Pure Python + the existing FastAPI/SQLAlchemy 2.x/
  Alembic/pytest stack.
- **No changes outside** `app/models/risk.py`, `app/models/__init__.py`,
  `app/schemas/risk.py`, `app/repositories/risk_repository.py`,
  `app/services/risk/**`, `app/api/routes/risk.py`, `app/main.py` (router
  registration), the one Alembic migration, the §10.3 pipeline hook in
  `app/services/ingestion/pipeline.py`, and the audit-actor fix in
  `app/core/audit.py` / `app/api/deps.py` documented above.
- mypy is not configured anywhere in this repo (Phase 0/1 never added it
  either) — all new code carries full type hints regardless, per spec §14.

## Phase 2 hardening — CHANGE_ORDER_Phase2_Hardening.md (complete)

Four independent changes, applied as named, in separate commits, with tests
written as each was implemented:

### CHANGE 1 — academic-decline signal's time axis

`internal_marks` (Phase 1, locked schema) had no real assessment date — the
academic-decline signal ordered "latest"/"baseline" by `created_at`, which is
import time, not assessment order. A college that bulk-imports a whole
term's marks in one file got a meaningless "decline."

Added an **optional** `internal_marks.assessment_date` column (migration
`6bf2927b6b7a`). Wired through ingestion as an optional mapping target for
`internal_mark` (`mapping.py`), with `normalizers.py::normalize_date` reused
as its normalizer, and loaded onto the canonical row in both the new-row and
existing-row-update paths of `canonical_loader.py::upsert_internal_mark`.

`signals/academic.py`'s bulk query now orders by
`COALESCE(assessment_date, created_at::date)`, tiebroken by `created_at` then
`id`. **No-regression guarantee**: when no row in a student's marks has
`assessment_date` set, `COALESCE` collapses to `created_at` for every row, so
the ordering is identical to before this change —
`test_academic_ordering_falls_back_to_created_at_when_no_assessment_date`
asserts this with the exact dataset/expected values that predate CHANGE 1.

### CHANGE 2 — validate `PUT /risk/config` payloads

`RiskConfigUpdateRequest.config` was a bare `dict`: a missing key, a typo'd
key, or `tier_cutoffs.watch >= high` reached `set_new_config()` unchecked,
surfacing as a crash or nonsensical tiering on the *next* recompute rather
than a 422 at the API boundary.

Added `RiskConfigModel` (+ nested `RiskWeights`, `TierCutoffs`) to
`schemas/risk.py`: `extra="forbid"` on every model, every numeric field
range-checked, and a `model_validator` enforcing `watch < high`.
`RiskConfigUpdateRequest.config` is now `RiskConfigModel`;
`routes/risk.py::update_config` calls `payload.config.model_dump()` before
handing it to the unchanged `set_new_config(session, tenant_id, dict, ...)`.
`test_default_config_is_valid` guards against the shipped
`DEFAULT_RISK_CONFIG` ever failing its own schema.

### CHANGE 3 — surface risk-recompute failures on the import batch

`_phase_risk_recompute` deliberately swallows recompute exceptions so a
recompute failure never flips an already-`COMPLETED` import to `FAILED`
(spec §10.3) — but that meant a partial/total recompute failure was
previously invisible to anyone not reading the worker logs.

Added `import_batches.risk_recompute_status` (`CHECK`'d to
`ok`/`partial`/`failed`/`skipped`) and `risk_recompute_summary` (jsonb,
migration `6bf2927b6b7a`, shared with CHANGE 1's column). 
`_phase_risk_recompute` derives status from the `RecomputeSummary` (any
per-student errors → `partial`; zero students evaluated → `skipped`;
otherwise → `ok`; an exception escaping `recompute_for_import_batch`
entirely → `failed`) and persists it via a new `_set_recompute_outcome()`,
in its own session/transaction so a failure there can't reach back into the
already-committed import. Exposed on `ImportBatchResponse`.

### CHANGE 4 — mypy + ruff (dev-only, user-confirmed)

Added `mypy==1.13.0` and `ruff==0.8.4` as a `dev` optional-dependency group
(`backend/pyproject.toml`) — never a runtime dependency. Pragmatic config:
ruff selects `E`/`F`/`I`/`B`/`UP` and ignores `B008` (FastAPI's `Depends()`
default-argument pattern, the framework's intended DI mechanism, not a bug);
mypy enables `disallow_untyped_defs`/`check_untyped_defs` with no plugins.

**ruff**: 39 issues against the existing tree, all mechanical — unused
imports/variables, `datetime.now(timezone.utc)` → `datetime.now(UTC)`
(`UP017`), `isinstance(x, (int, float))` → `isinstance(x, int | float)`
(`UP038`), a `for`-loop `yield` → `yield from` (`UP028`), a bare `raise` in
an `except` → `raise ... from` (`B904`), and line-length wraps. All fixed;
`ruff check app tests` is clean.

**mypy**: 75 pre-existing errors against the existing tree. Per the change
order's explicit instruction ("if a large number of pre-existing errors
surface, STOP and report categories rather than mass-suppress"), this
backlog is reported, not mass-fixed with `type: ignore`. Categories:

- **~50 errors, one root cause**: `session.get(ImportBatch, ...)` returns
  `ImportBatch | None` and is used unchecked for the rest of each pipeline
  phase function in `services/ingestion/pipeline.py` (and similarly for
  `Student | None` in `canonical_loader.py`). This is a Phase 0/1 invariant
  — the caller always created the row earlier in the same transaction —
  that mypy has no way to see. Fixing it properly means an `assert`/narrow
  at each of ~15 call sites across a file this change order didn't name;
  left as a follow-up, not done here.
- **Untyped pre-existing functions** (`no-untyped-def`): `cleaning/
  validators.py`, `resolution/identity.py`, `reconciliation/conflicts.py`,
  `core/audit.py`, `canonical_loader.py`, `repositories/base.py`.
- **Dynamic `type[Base]` dispatch losing attribute info** (`attr-defined`):
  `repositories/base.py`'s generic `_model: type[T]` pattern, `core/
  audit.py`'s `target.__class__` dispatch in the mapper-event hooks — the
  same category of issue this session fixed in `engine.py`'s
  `_ENTITY_MODEL_BY_TYPE`, but for two files outside this change order's
  named scope.
- **`Sequence` vs `list` return-type mismatches**: `routes/sources.py`,
  `routes/mappings.py`, `routes/imports.py` return `.scalars().all()`
  (`Sequence`) where the response model / type hint says `list` — the same
  pattern this session fixed in `risk_repository.py` and `routes/risk.py`,
  for three files outside this change order's named scope.
- **One `callable` builtin used as a type annotation** in `normalizers.py`'s
  `FIELD_NORMALIZERS: dict[str, dict[str, callable]]` (should be
  `typing.Callable`).
- **One FastAPI exception-handler signature mismatch** in `core/
  exceptions.py` (`add_exception_handler`'s stub is imprecise about async
  handlers — a known FastAPI/Starlette typing friction point).
- **One `pydantic-settings` `Settings()` call-arg mismatch** in `core/
  config.py` (fields are populated from the environment at runtime; mypy
  can't see that from the call site).

The handful of mypy errors that were direct fallout of this session's own
typing work (`engine.py`'s `_persist_one`/`_student_ids_for_entity_rows`,
`risk_repository.py`'s `list_at_risk`, `routes/risk.py`'s
`_assessment_to_response`) are fixed, not reported.

Added `.github/workflows/backend-ci.yml`: a `lint` job (ruff blocking, mypy
`continue-on-error: true` until the backlog above is paid down) and a `test`
job (`pytest`, relying on `testcontainers` to provision its own Postgres —
no extra service config needed on `ubuntu-latest`).

### Acceptance results

Full suite: **101/101 passing** (89 Phase 0/1/2 + 12 new: 2 signal-ordering +
2 ingestion tests for CHANGE 1, 4 API + 1 scoring test for CHANGE 2, 3 engine
tests for CHANGE 3). `test_rls_coverage.py` green, unchanged.

### A bug found and fixed along the way (not named in the change order)

Writing CHANGE 1's ingestion tests surfaced a pre-existing bug: `internal_mark`
and `fee` rows have `Decimal` fields (`normalize_number`'s output) that were
being passed straight into `StagingRecord.cleaned_payload`, a `jsonb` column
— psycopg's JSON encoder doesn't know how to serialize `Decimal`, so every
such row failed at the cleaning phase. Same category as the Part A
audit-actor bug: caught by acceptance tests, not by the change order, fixed
and called out rather than worked around. Added
`normalizers.py::to_jsonable()`, applied only at the JSONB-storage boundary
in `pipeline.py::_phase_clean`, never to the dict `validators.py` validates
(its range checks need real `Decimal`/numeric types).

### Confirmations

- **No new runtime dependencies.** `mypy`/`ruff` are a `dev`-only
  optional-dependency group, confirmed with the user before adding (CHANGE
  4 required explicit confirmation per the change order).
- **No changes outside** the files named per change above, plus the one
  shared Alembic migration (`6bf2927b6b7a`, CHANGE 1 + CHANGE 3 schema) and
  the Decimal/JSONB bugfix called out above.
- Six commits: the shared migration, CHANGE 1, CHANGE 2, CHANGE 3, CHANGE 4,
  and the Decimal/JSONB bugfix — each independently reviewable.

## Phase 2 hardening, part 2 — CHANGE_ORDER_Phase2_Hardening_Part2.md (complete)

### CHANGE 1 — enforce `NOT NULL` on `internal_marks.student_id`/`course_id` and `fees.student_id`

Both tables had nullable `student_id`/`course_id` per the original Phase 2
spec §6's literal column list ("student_id uuid", no `NOT NULL`), which left
the natural-key unique constraints (`uq_internal_marks_natural_key`,
`uq_fees_natural_key`) unable to prevent duplicates across rows where the
column is `NULL` — Postgres treats every `NULL` as distinct for uniqueness
purposes. A real gap in the dedup guarantee, not cosmetic.

**Step 1a confirmation, before writing anything**: no persistent
environment exists for this project yet — only the ephemeral testcontainers
Postgres each test run spins up and tears down — so there was no live data
to inspect for existing nulls. Instead confirmed structurally, by reading
every code path that can write these tables:
- `canonical_loader.py::upsert_internal_mark` resolves a student (by
  `roll_no`) and a course (by `course_code`) and raises
  `UnresolvedReferenceError` for either failure *before* constructing the
  `InternalMark(...)` row — it is not possible for application code to
  reach the ORM constructor with a null `student_id`/`course_id`.
  `upsert_fee` has the identical guarantee for `student_id`.
- `_phase_resolve_and_load` (`pipeline.py`) catches `UnresolvedReferenceError`
  per row and quarantines it (`validation_status="quarantined"`, a recorded
  reason) — never drops it, never lets it reach the loader's `session.add()`.
- `validators.py::REQUIRED_FIELDS` already requires `roll_no`/`course_code`
  to be *present* in the payload for `internal_mark`/`fee`, quarantining
  before resolution is even attempted if they're missing.
- The only raw-SQL test fixtures that insert into these tables
  (`tests/test_risk_signals.py::_mark`/`_fee`) take `student_id`/`course_id`
  as required positional parameters with no `None` default.

No conflicting case found — proceeded as the change order anticipated.

**One deviation from the change order's assumption**: step 1e #2 asks to
"confirm (re-run) the existing acceptance test suite that already covers
unresolved-reference quarantine (Phase 1 spec §15 / 'unresolved-reference
quarantine')." No test under that description exists in this codebase —
grepped the full Phase 0/1 spec and the test suite for "unresolved-reference"
and for the `UnresolvedReferenceError` message text; neither matched
anything. The closest existing test
(`test_student_missing_roll_no_is_quarantined`) covers a *missing required
field*, not an *unresolvable reference* (a present `roll_no`/`course_code`
that doesn't match any existing canonical row). Rather than silently
treating an assumption as fact, this is reported here, and CHANGE 1's new
tests below fill the actual gap by exercising the DB-level backstop
directly — chosen over a pipeline-level quarantine test because, per the
investigation above, defense-in-depth already sits entirely at the
application layer (validators + loader); the DB constraint is reachable
only by code that bypasses that layer entirely, which is exactly what the
new tests construct.

**Migration** (`d67e374fb99f`, autogenerated against the model changes
below — `alembic check` confirms no remaining drift):
```sql
ALTER TABLE fees ALTER COLUMN student_id SET NOT NULL;
ALTER TABLE internal_marks ALTER COLUMN student_id SET NOT NULL;
ALTER TABLE internal_marks ALTER COLUMN course_id SET NOT NULL;
```
`fees.course_id` does not exist on the canonical model (fees are not
course-scoped) — confirmed before writing the migration, not touched, per
the change order's explicit instruction not to invent it.

**Models** (`app/models/canonical.py`): `InternalMark.student_id`,
`InternalMark.course_id`, `Fee.student_id` changed from
`Mapped[uuid.UUID | None]` to `Mapped[uuid.UUID]`. The code comment
documenting the old nullable-FK gap is updated in place to describe the
guarantee now in force, rather than removed outright — it still explains
why the unique constraints exist and now actually hold.

**Validators**: no change. Confirmed already in force (see step 1a above);
the new `NOT NULL` constraints are a backstop, not the primary defense.

**Tests** (`tests/test_ingestion_pipeline.py`): three new tests —
`test_internal_mark_requires_student_id_at_the_db_layer`,
`test_internal_mark_requires_course_id_at_the_db_layer`,
`test_fee_requires_student_id_at_the_db_layer` — each constructs the
canonical row directly via the ORM with the relevant column forced to
`None` (bypassing `canonical_loader.py` entirely, which the application
never does) and asserts `session.flush()` raises `IntegrityError`. Three
tests rather than one because the migration enforces three independent
constraints across two tables; each is asserted once, not duplicated.

### Acceptance results

Full suite: **104/104 passing** (101 + 3 new). `test_rls_coverage.py`
green, unaffected (no RLS change in this part). `ruff check app tests`
clean. mypy: still exactly 75 pre-existing errors (unchanged from Phase 2
hardening part 1) — this change introduced no new typing debt.

### Confirmations

- **No new dependencies.**
- **No changes outside** `app/models/canonical.py`, the one new migration
  (`d67e374fb99f`), and the new tests in `tests/test_ingestion_pipeline.py`.
- One commit.

## Phase 3, PART A + PART C — `IMPLEMENTATION_GUIDE_Phase3_PartA_Frontend_SeedData.md` (backend + seed data complete; PART B frontend tracked separately)

### PART A — backend additions

**A.1 CORS**: `CORSMiddleware` added in `app/main.py`, origins from new
`FRONTEND_ORIGINS` env var (`app/core/config.py`, default
`http://localhost:5173`). `allow_credentials=False` — auth is Bearer-token-
in-header (existing JWT scheme), never cookies, so credentialed CORS was
never needed; combining `allow_origins=["*"]` with credentials is the
specific footgun the guide warned against, and neither side of that
combination is in play here.

**A.2/A.3 `GET /risk/summary`, `GET /risk/summary/by-department`**: implemented
as two new `RiskRepository` methods (`summary`, `summary_by_department`),
reusing the exact role-scoping path `GET /risk/students` already uses
(`visible_student_ids` + `has_full_visibility`) — privileged roles see the
whole tenant, faculty see only their `faculty_scopes`, student role is
rejected by `_ensure_not_student_role` (403, same as the rest of `/risk/*`).
Each is one or two `GROUP BY` aggregate queries regardless of student count
(§A.5.5's no-N+1 acceptance test asserts this directly by counting SQL
statements via a `before_cursor_execute` listener at N=3 vs N=33 students).

Decisions where the guide was silent:
- **`generated_at`** is wall-clock time at response construction, not a
  derived "freshest underlying data" timestamp — the guide's example JSON
  doesn't define which, and "when was this summary generated" is the more
  natural reading of the field name.
- **`by-department` ordering** is alphabetical by department label
  (`"Unassigned"` sorts in place, not pinned last) — the guide's example
  order (CSE, then Unassigned) isn't asserted as a contract anywhere in
  PART B's bindings, so no special-casing was added for it.
- **`"Unassigned"` bucket** is `Department.code` resolved via `Student ->
  Programme -> Department`, `COALESCE`'d to the literal string
  `"Unassigned"` when unresolvable (no programme, or a programme with no
  department) — exactly §B.4's instruction not to conflate "no department"
  with "no mentor".

### A bug found and fixed along the way (not named in the guide)

Running `scripts/seed_demo.py` against a real Postgres surfaced a second
instance of the same bug class as Phase 2 hardening part 1's "Decimal/JSONB"
fix (above): `app/core/audit.py::_serialize()` converts `UUID` and
date-like values for the JSONB `audit_log.old_value`/`new_value` snapshot,
but never handled `Decimal` — so any **direct** ORM write of an
`InternalMark`/`Fee` row with a real `Decimal` value (`max_marks`,
`obtained`, `amount_due`, `amount_paid`) crashed on `session.flush()` with
`TypeError: Object of type Decimal is not JSON serializable`. The ingestion
pipeline never hits this: `canonical_loader.py`'s callers always construct
these rows from `StagingRecord.cleaned_payload`, which the Phase 2 fix
already float-ifies via `to_jsonable()` before it's ever stored — so by the
time `cleaned["max_marks"]` reaches the ORM constructor it's already a
`float`, not a `Decimal`. `scripts/seed_demo.py` (per §C.1.5, writing
canonical rows directly, bypassing ingestion on purpose) does not go
through that float-ifying boundary, so it hit the bug immediately on the
first `InternalMark` insert. Reproduced independently of the seed script
with a minimal ORM-only repro (both against the dev DB and inside the
testcontainers test environment) before fixing, to confirm it's a general
latent bug and not seed-script-specific.

**Fix**: `_serialize()` now converts `Decimal -> float`, the identical
conversion `to_jsonable()` already uses for the same reason, in the
one place that was missing it. **New regression test**
(`tests/test_ingestion_pipeline.py::test_internal_mark_with_decimal_values_writes_audit_row_without_error`)
constructs an `InternalMark` with genuine `Decimal` values directly via the
ORM (the exact pattern `seed_demo.py` uses) and asserts the flush succeeds
and the resulting `audit_log.new_value` round-trips as JSON-safe floats.

### PART A acceptance results

`tests/test_risk_summary.py` (new, 5 tests): tier/type counts correct;
faculty-vs-privileged role scoping; tenant isolation; `by-department`
grouping incl. the `Unassigned` bucket; bounded query count regardless of
student count. Full suite: **110/110 passing** (109 prior + 1 new
regression test for the audit bug above; `test_risk_summary.py`'s 5 tests
bring the file-level count to 110 — the 1 net test beyond "104 + 5" reflects
the regression test, not double-counting). `test_rls_coverage.py` green,
unaffected (no new tables). `ruff check app tests scripts` clean. `mypy`:
still exactly 75 pre-existing errors, unchanged — no new typing debt.

### PART C — seed / test data

`scripts/seed_demo.py` (idempotent: skips data creation and just
recomputes if the `demo-eng` tenant already exists) creates tenant "Demo
Engineering College", the three named users (`principal`, `meera.iyer`
faculty scoped to `department=CSE`, `admin`), CSE/MECH/ECE/CIVIL
departments + programmes, CSE courses (DBMS/OS/CN/TOC), the named CSE
cohort from §C.2, ~17 clean filler CSE students, and ~55 other-department/
unassigned students with a deterministic clean/watch/high profile mix —
then calls `recompute_for_tenant` once and prints credentials, tenant id,
and tier counts.

Verified end-to-end against a real Postgres instance (not just unit-level
reasoning): every named-cohort student's attendance/marks/fee inputs were
first checked against the live `RulesRiskEvaluator` in isolation to confirm
they produce exactly the findings/tier the spec table names, *then* the
full script was run against a migrated dev database. Result: `evaluated=79
changed=79 unchanged=0 skipped=0 errors=0`, tier counts `{low: 59, watch:
13, high: 7}`. Re-running is idempotent (`changed=0 unchanged=79`, no
duplicate rows). A real API smoke test (login as each seeded user, hit
`/risk/students`, `/risk/summary`, `/risk/summary/by-department`,
`/risk/students/{id}`, `/risk/interventions?student_id=`) confirmed every
§C.6 verification point: the faculty board shows exactly Aarav/Mohammed/
Sneha/Ananya/Diya (watch+high) and excludes Rohit/Karthik (low); the
principal's dashboard summary and by-department tiles are populated;
Aarav's 360 shows all 3 expected findings, a worsening history
(low→watch→high across three assessments — the two oldest seeded directly
as `is_current=false` history rows since the engine only ever computes
"today"), and the completed `mentor_meeting` intervention; Ananya's
assessment carries `subject_minor_status: "minor"`; and a `parent_contact`
intervention attempt for Ananya without `guardian_consent_confirmed`
correctly 403s (Phase 2 §9 enforcement, exercised here, not re-implemented).

Decisions where §C.2's table was silent or only approximate:
- The table's attendance percentages are illustrative ("60% over ~100
  sessions"), not exact fractions of the session counts chosen — two
  students land one rounding step off the table's literal percentage
  (Ananya/Diya compute to 70% over 30 sessions, not 71%; Karthik to 96%
  over 50, not 95%) because those session counts don't divide evenly into
  the stated percentage. The **rule outcomes are identical either way**
  (verified against the live evaluator, see above) — what matters per the
  guide's own framing note is the findings/tier, not the cosmetic percentage.
- Attendance session sequences use a deterministic even-distribution
  algorithm (`even_spread`, a Floyd's-algorithm-style "evenly place k of n"
  generator) rather than a fixed pattern, so that any 12-session trend
  sub-window stays close to the overall percentage — this is what keeps
  students meant to trigger only `ATTENDANCE_BELOW_THRESHOLD` from also
  spuriously triggering `ATTENDANCE_DECLINING`, confirmed by direct
  evaluator runs for every named-cohort and filler/other-department profile
  before committing to the values.
- Aarav's "worsening history" and "completed mentor-meeting intervention"
  (§C.6's verification script, not named as a build requirement in §C.1-C.4)
  were added since §C.6 explicitly checks for them: two `is_current=false`
  `RiskAssessment` rows are inserted directly at `now() - 60d` (low, score
  10) and `now() - 21d` (watch, score 35), so the 360's history timeline
  shows low → watch → high leading into today's engine-computed current
  assessment; one `completed` `mentor_meeting` `Intervention` + outcome is
  added for the same reason.
- The ~40-other-department / ~15-unassigned split (§C.3/C.4, both
  explicitly "exact counts don't need to match") uses a deterministic
  70/20/10 clean/watch/high profile mix by student index, not randomness —
  reproducible across re-seeds of a dropped-and-recreated tenant, which
  matters for review/debugging even though the script's own idempotency
  path (skip-if-exists) doesn't depend on it.

`scripts/sample_data/*.csv` (`students.csv`, `attendance.csv`,
`internal_marks.csv`, `fees.csv`) follow §C.5's exact header shapes,
extended from the guide's 1-3-line examples to a handful of rows each
(still "small", per the guide's own framing) across the same four
named-cohort students so the set is internally consistent for manual
testing. Verified by actually running the full `create source → create
mapping → upload → recompute` flow against the seeded `demo-eng` tenant for
all four entity types: all rows loaded, zero quarantined,
`risk_recompute_status: "ok"` for every batch. (The demo tenant was reset
and re-seeded from scratch afterward, since this verification's uploads
would otherwise have mixed extra attendance/marks/fee rows into the
canonical seed's carefully-tuned named-cohort data.)

### PART C confirmations

- **No new runtime dependencies** (the verification script used `httpx`,
  already a transitive dependency of the `test` extra; not added to
  `pyproject.toml`'s runtime deps).
- **Backend changes limited to**: `app/core/config.py`, `app/main.py`,
  `app/repositories/risk_repository.py`, `app/schemas/risk.py`,
  `app/api/routes/risk.py`, `app/core/audit.py` (the bug fix above),
  `tests/test_risk_summary.py` (new), `tests/test_ingestion_pipeline.py`
  (one new regression test), `.env.example`, plus the new
  `scripts/seed_demo.py` and `scripts/sample_data/*.csv`. No migrations —
  PART A added no new tables/columns.

## Phase 3, PART B — frontend (`IMPLEMENTATION_GUIDE_Phase3_PartA_Frontend_SeedData.md` §B, complete)

New Vite + React + TypeScript app at `frontend/`, implementing the approved
`Risk Copilot.dc.html` design (Institution overview, Student 360, Risk
Board, empty/error/stale states) against the live API. All risk
scores/tiers/findings rendered are engine-computed, fetched from PART A's
endpoints — the mockup's numbers were illustrative only and are not
hardcoded anywhere in the app.

### Stack and decisions made where `IMPLEMENTATION_SPEC_Phase3.md` was
missing (per the user's earlier "proceed with sensible defaults" call)

- **Vite + React 18 + TypeScript**, React Router v6 for routing, TanStack
  Query for server state/caching, Axios for HTTP.
- **Auth**: JWT access/refresh matching `auth.py`'s existing contract — no
  new backend auth surface. Tokens in memory + `localStorage` (documented
  in `tokenStorage.ts` as never trusted for authorization decisions, only
  for UI state; the server remains the only security boundary). A single
  in-flight refresh promise in the Axios response interceptor collapses
  concurrent 401s into one `/auth/refresh` call; refresh failure clears
  tokens and routes to `/login`.
- **Types**: generated via `openapi-typescript` against the live
  `/openapi.json`, re-exported by name from `src/api/types.ts` rather than
  used inline, so a future schema regen only needs review at one file.
- **a11y**: basic — labeled form fields, semantic roles for tier badges
  (not color-only: `SHAPE` tokens give high/watch/low distinct glyphs,
  per the design's colour-vision-safe treatment), focus-visible states on
  interactive elements.
- **Role gating is UX-only** (`RequirePrivileged`/`RequireAdmin` hide
  nav items and routes), explicitly commented in `RequireAuth.tsx` as not
  the real boundary — `GET /risk/summary` etc. already enforce role/tenant
  scope server-side regardless of what the frontend shows.

### Bug found and fixed during verification: stale post-sign-out redirect

Browser verification (faculty sign-out → principal login, same tab)
surfaced a real bug: the principal's login landed on the faculty user's
last-visited `/students/<id>` page instead of `/board`/`/dashboard`.

Root cause: `RequireAuth`'s redirect (`<Navigate to="/login"
state={{from: location}} replace />`) attaches the page being left as
`from` for *any* unauthenticated render — including the deliberate
sign-out flow — and `history.state` survives a full reload, so that stale
`from` could be picked up by the next login on the same tab. Reordering
the sign-out handler's `logout()`/`navigate()` calls did not fix it: added
debug logging confirmed `RequireAuth` re-fires against the *pre-navigate*
location after the explicit `navigate(..., {state: null})` call had
already committed, because the imperative navigate's history update and
the auth context's `user = null` update don't reliably land in the same
React commit — so `RequireAuth`'s stale-location render clobbers the
explicit redirect's `state: null` with its own `{from: <old page>}`.

Fixed with a plain module-level flag (`voluntarySignOut` in
`RequireAuth.tsx`), not React state, since the failure mode is exactly a
render-timing race that React state updates don't protect against: the
sign-out handler sets it synchronously before calling `logout()`;
`RequireAuth` checks it (no React render dependency) and omits `from`
when set, however many times it re-fires before `/login` actually mounts;
`LoginPage` clears it on mount so a later genuine session-expiry redirect
on the same tab still gets a correct `from`. Verified via Playwright:
`history.state` after sign-out is now `{"usr":null,...}` (was previously
carrying the stale `from`), and the principal's subsequent login lands on
`/board` as designed.

### Verification (Playwright against the seeded `demo-eng` tenant)

- **Faculty** (`meera.iyer@demo-eng.edu`, CSE-scoped): Risk Board shows
  exactly the 5 CSE students at watch/high tier (Aarav 95, Mohammed Faiz
  50, Sneha Reddy 40, Ananya Nair 40, Diya Patel 40) with correct tier
  colour/shape, no Dashboard nav item; Aarav's Student 360 shows all 3
  findings, the worsening assessment history, and the completed
  mentor-meeting intervention; Ananya's 360 shows the minor badge; logging
  a `parent_contact` intervention for a minor student correctly routes
  through the consent-gate step before the entry is recorded.
- **Principal** (full visibility): Dashboard renders 79 assessed across 5
  departments, KPI tiles (7 high / 13 watch / 59 low), the risk
  distribution bar, by-department breakdown including the "NO DEPARTMENT"
  tag for Unassigned, the "Trend builds as risk data accumulates" empty
  placeholder (correct — single recompute, no history to chart yet), and
  the top-5 highest-risk-now list.
- `npx tsc -p tsconfig.app.json --noEmit` clean.
- Browser console errors: none, across both role flows.

### PART B confirmations

- **No backend changes** beyond PART A/C (no new endpoints, fields, or
  runtime deps were added to support the frontend).
- **No frontend fields invented**: every rendered value traces to a field
  in the generated OpenAPI types; the findings view-model
  (`findingViewModel.ts`) reads each rule's actual evidence keys (e.g.
  `value`/`threshold`, `prior_pct`/`recent_pct`, `baseline_pct`/
  `latest_pct`, `failing_count`, `overdue_days`) rather than the mockup's
  illustrative `ev` shape.

### PART C re-verification note

Re-verified after PART B: `seed_demo.py` re-run against `demo-eng` confirms
idempotency (`changed=0 unchanged=79`); a direct DB query confirms all 7
named-cohort students' score/tier/finding-codes match §C.2 exactly. The
C.5 sample CSVs were re-verified through the real import API using a
disposable tenant (`csv-verify-tmp`, dev Postgres only) instead of
`demo-eng`, to avoid repeating the earlier mid-build CSV-verification
pollution-and-reset cycle — all four batches completed with 0 quarantined
rows.

That throwaway tenant is intentionally **not** hard-deleted afterward: the
app's own DB role (`app_user`) has no `DELETE` grant on most
tenant-scoped tables (e.g. `intervention_outcomes`) — an append-only/
audit-safety property of the schema, not an oversight — so removing it
would require superuser SQL outside the app's normal data-access path.
Left in place in the dev-only Postgres container; harmless (isolated by
`tenant_id`/RLS, doesn't touch `demo-eng`). The scratchpad verification
scripts now reuse this one fixed tenant/source on every re-run instead of
creating a new one each time, so the artifact doesn't multiply.
