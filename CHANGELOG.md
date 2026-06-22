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

## Phase 1 — not started yet
