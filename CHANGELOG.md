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
