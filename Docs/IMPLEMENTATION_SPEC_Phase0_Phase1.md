# IMPLEMENTATION SPEC — Phase 0 & Phase 1
### Foundation + Unified-Data-Ingestion (single source of truth) for the AI College Copilot
### This document is the contract. Build to it exactly.

---

## 0. How to use this document (READ FIRST — instructions for the AI coding agent)

You are implementing **Phase 0 (foundation)** and **Phase 1 (data ingestion → single source of truth)** of a multi-tenant SaaS. Obey these rules for the entire build:

1. **This document is the single source of truth.** Do **not** invent tables, columns, endpoints, libraries, or folder names that are not specified here. If something is ambiguous or missing, **stop and ask** — do not guess and do not "fill in" with plausible-looking code.
2. **Do not add a dependency** without first listing it, its purpose, and waiting for confirmation. Pin current stable versions.
3. **Every tenant-owned table MUST have `tenant_id`.** Every read/write MUST be tenant-scoped. **Never** disable or bypass Row-Level Security. The app connects as a **non-superuser** role.
4. **All schema changes go through Alembic migrations.** Never mutate the DB outside a migration. Never edit a past migration that has run — add a new one.
5. **Follow the directory structure in §3 exactly.** One responsibility per module. No god-files.
6. **Write the tests in §9 as you build** — they are the definition of done, not an afterthought. A phase is not complete until its acceptance tests pass.
7. **Idempotency is mandatory.** Re-running any ingestion step on the same input must produce the same result with zero duplicates and zero data loss.
8. **Never hard-delete canonical data, never silently overwrite conflicting values, never drop a bad row.** Bad rows are quarantined (kept), conflicts are flagged, deletes are soft.
9. Commit in small, reviewable units (one stage / one module per commit). Keep a running `CHANGELOG` of what you built vs this spec.
10. When you finish a section, **report back which acceptance tests pass** before moving on.

---

## 1. System context & non-negotiable principles

We are building an **AI layer on top of** colleges' existing systems (ERPNext, Fedena, MasterSoft, TCS iON, Excel, Sheets, LMS, biometric, payments). Phase 1 ingests their messy data and turns it into **one canonical source of truth (SoT)** that all future features (student-risk engine, NL query, accreditation) read from.

**Principles (apply everywhere):**
- **Three-layer data flow (medallion):** `RAW (immutable) → STAGING (cleaned/validated) → CANONICAL (SoT)`. Data only ever flows forward; earlier layers are never mutated by later stages.
- **No data loss:** raw layer is append-only and immutable; the original uploaded file is retained byte-for-byte; rows that fail validation are **quarantined with reasons**, never dropped.
- **No duplicates:** a deterministic identity map + idempotent upserts guarantee one canonical entity per real-world entity, even across repeated imports and multiple sources.
- **No inconsistency:** each import is transactional per entity-type; conflicting values are resolved by an explicit precedence policy and logged, never silently overwritten.
- **No leakage:** Postgres RLS + app-layer tenant scoping (defense in depth); tenant context derived from the authenticated session **server-side only**, never from client/file input.
- **Full provenance & audit:** every canonical row is traceable to its source system, source record, and import batch; every change is recorded in an append-only audit log.
- **Modularity & SRP:** layered architecture (api → service → repository → model); the ingestion pipeline is a sequence of independent, idempotent, resumable stages.
- **Connector-agnostic from day one:** CSV/Excel is just the first connector behind a generic `Connector` interface, so API connectors (ERPNext, Fedena) slot into the same staging→canonical pipeline later without rework.

---

## 2. Tech stack (locked)

| Concern | Choice |
|---|---|
| Language / framework | Python 3.12+, **FastAPI** |
| ORM / migrations | **SQLAlchemy 2.x (typed, mapped classes)** + **Alembic** |
| DB driver | psycopg 3 |
| DB | **PostgreSQL 16+** |
| Validation / DTOs | Pydantic v2, pydantic-settings |
| File parsing | pandas + openpyxl (xlsx), built-in csv |
| Auth | JWT (PyJWT), password hashing **argon2** (argon2-cffi) |
| Tests | pytest, testcontainers or a disposable Postgres |
| Frontend (later, Cursor) | React + Vite + TS + Tailwind + shadcn/ui |
| Deploy | Backend+DB on Railway/Render/Fly; frontend on Vercel |

Do not introduce Celery/Kafka/Spark/dbt now. Pipeline runs in-process (FastAPI background task) for Phase 1; the design must allow swapping to a queue later **without changing stage logic**.

---

## 3. Repository structure (create exactly this)

```
backend/
  app/
    main.py
    core/
      config.py          # pydantic-settings; all env vars
      db.py              # engine, SessionLocal, get_session
      rls.py             # set_tenant_context() / reset — SET LOCAL app.current_tenant
      security.py        # JWT encode/decode, argon2 hash/verify
      audit.py           # audit-log writer
      logging.py
      exceptions.py      # typed app exceptions + handlers
    models/
      base.py            # Base; mixins: PKMixin, TenantMixin, TimestampMixin,
                         #   SoftDeleteMixin, ProvenanceMixin
      tenant.py          # Tenant
      user.py            # User
      ingestion.py       # SourceSystem, ColumnMapping, ImportBatch, RawFile,
                         #   RawRecord, StagingRecord
      identity.py        # EntityIdentityMap, MergeReviewItem
      canonical.py       # Student, Faculty, Department, Programme, Course,
                         #   Enrollment, Attendance, InternalMark, SemesterResult, Fee
      audit.py           # AuditLog
      conflict.py        # DataConflict
    schemas/             # Pydantic request/response models (DTOs only)
    repositories/        # tenant-scoped data access; NO business logic
      base.py            # TenantRepository base (auto-applies tenant filter)
      ...
    services/
      auth_service.py
      ingestion/
        pipeline.py            # orchestrator / state machine
        connectors/
          base.py              # Connector ABC: discover(), read_rows()
          csv_excel.py         # first concrete connector
        parsing.py             # bytes -> RawRecord rows
        mapping.py             # apply ColumnMapping -> normalized field names
        cleaning/
          normalizers.py       # per-type normalization (date, rollno, phone, etc.)
          validators.py        # per-entity validation rules
        resolution/
          resolver.py          # entity resolution logic
          identity.py          # identity-map read/write
        loading/
          canonical_loader.py  # idempotent upsert into canonical SoT
        reconciliation/
          anomalies.py
          completeness.py
          conflicts.py         # conflict detection + precedence policy
    api/
      deps.py            # get_current_user, get_tenant_session
      routes/
        health.py
        auth.py
        sources.py       # register source systems
        mappings.py      # CRUD column mappings
        imports.py       # upload file, trigger pipeline, batch status, DQ report
        students.py      # Student 360 read (proof-of-life query)
  migrations/            # alembic
  tests/
  alembic.ini
  pyproject.toml
  Dockerfile
docs/
  IMPLEMENTATION_SPEC.md  # this file
```

---

## 4. PHASE 0 — Foundation

### 4.1 Base mixins (`models/base.py`)
- `PKMixin`: `id UUID PK default gen_random_uuid()`.
- `TenantMixin`: `tenant_id UUID NOT NULL` + index; FK → `tenants.id`.
- `TimestampMixin`: `created_at`, `updated_at` (server defaults; `updated_at` on update).
- `SoftDeleteMixin`: `is_deleted BOOLEAN NOT NULL default false`, `deleted_at`.
- `ProvenanceMixin`: `source_system_id UUID NULL`, `source_record_id TEXT NULL`, `import_batch_id UUID NULL`, `ingested_at TIMESTAMPTZ`.

### 4.2 Auth & tenancy
- `tenants(id, name, slug UNIQUE, created_at, is_active)`.
- `users(id, tenant_id, email, password_hash, role, is_active, created_at)`; UNIQUE `(tenant_id, email)`; `role IN ('admin','principal','registrar','iqac','faculty','student')`.
- JWT payload: `{ sub: user_id, tenant_id, role, exp }`. Short-lived access token + refresh token. Argon2 password hashing.
- `api/deps.py::get_current_user` decodes JWT. `get_tenant_session` opens a DB session **and** sets the tenant context (§4.3) inside the transaction.

### 4.3 Row-Level Security (do this in Phase 0, not later)
- App connects as a dedicated **non-superuser** role `app_user` (RLS applies; cannot bypass).
- For **every** table with `tenant_id`, in its migration:
  ```sql
  ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
  ALTER TABLE <t> FORCE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON <t>
    USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid);
  ```
- `core/rls.py`: at request start, within the transaction, run
  `SET LOCAL app.current_tenant = '<tenant_id from JWT>';`
  Tenant id comes **only** from the verified JWT — never from a header, query param, or file.
- **Defense in depth:** `repositories/base.py` ALSO adds an explicit `WHERE tenant_id = :tenant` to every query. RLS is the floor, not the only guard.

### 4.4 Audit log (`models/audit.py`)
- `audit_log(id, tenant_id, table_name, record_id, action ['insert','update','soft_delete'], old_value JSONB, new_value JSONB, actor_user_id, at)` — **append-only**.
- Implement via SQLAlchemy event hooks (or DB triggers) on canonical tables. No update/delete on this table ever.

### 4.5 Cross-cutting
- `core/config.py`: all secrets/URLs via env; never hardcode.
- `core/exceptions.py`: typed exceptions + FastAPI handlers returning consistent error JSON.
- `routes/health.py`: `/health` (liveness) + `/health/db` (DB round-trip).
- Structured logging with request id + tenant id (never log secrets or full PII payloads).
- **Deploy the empty app end-to-end on day 1.**

### 4.6 Phase 0 Definition of Done
Deployed app reachable; login issues JWT; migrations run clean; RLS enabled + **verified by test** (§9.4); audit log writes on canonical insert/update; `/health/db` green; CI runs the test suite.

---

## 5. PHASE 1 — Ingestion pipeline (RAW → STAGING → CANONICAL)

### 5.1 Pipeline state machine (`services/ingestion/pipeline.py`)
An `ImportBatch` moves through states; each transition is **idempotent and resumable**:
```
RECEIVED → PARSED → MAPPED → CLEANED → RESOLVED → LOADED → RECONCILED → COMPLETED
                                  │                                   
                                  └─(unrecoverable)→ FAILED   (rows → QUARANTINED, batch not partially loaded)
```
Rules: a stage reads from the previous layer and writes the next; never mutates the previous; can be re-run safely; on failure marks the batch + reasons and leaves canonical untouched.

### 5.2 LAYER 1 — RAW (immutable, append-only) → guarantees *no data loss*
- `import_batches(id, tenant_id, source_system_id, uploaded_by, original_filename, content_hash, entity_type, status, row_count_raw, row_count_loaded, row_count_quarantined, error, started_at, finished_at)`.
- `raw_files(id, tenant_id, import_batch_id, storage_uri, original_filename, content_hash, byte_size)` — store the **original file unchanged** (object storage or large-object/blob). Retained for recovery & audit.
- `raw_records(id, tenant_id, import_batch_id, row_number, raw_payload JSONB)` — each source row captured **verbatim** as JSON before any transformation. Append-only.
- **Idempotent upload:** compute `content_hash` (sha256). If an identical file for the same source already exists → do not re-create raw rows; return the existing batch (warn). This stops accidental double-imports at the door.

### 5.3 Column mapping (`mapping.py`) → handles *messy, inconsistent headers*
- `column_mappings(id, tenant_id, source_system_id, entity_type, mapping JSONB, version, created_at)`.
- `mapping` = `{ "canonical_field": "their_source_header", ... }` + per-field type hints.
- Mappings are **saved and reused** per source+entity so repeat imports are consistent. Expose CRUD via `routes/mappings.py` and a "suggest mapping" helper (fuzzy header→canonical-field matching the user confirms).
- Unmapped/extra columns are preserved in `raw_payload` (never discarded).

### 5.4 LAYER 2 — STAGING (clean, type, validate) → *processing + simplifying*
- `staging_records(id, tenant_id, import_batch_id, entity_type, cleaned_payload JSONB, validation_status ['valid','quarantined'], validation_errors JSONB, resolved_entity_id UUID NULL)`.
- **Normalizers (`cleaning/normalizers.py`)** — pure functions, unit-tested, per field type:
  - dates → ISO (handle `dd/mm/yyyy`, `dd-mm-yy`, Excel serials); roll numbers → trimmed/upper/canonical format; names → trimmed, collapsed whitespace, title-cased for storage (keep raw); phone → digits only + country norm; gender/category → controlled vocab; numbers → strip `%`, commas; empty/`"N/A"`/`"-"`/`"NULL"` → real `NULL`.
- **Validators (`cleaning/validators.py`)** — per entity: required fields present, types correct, ranges sane (marks 0–max, attendance 0–100, dob plausible). 
- **Quarantine, never drop:** a row failing validation is written with `validation_status='quarantined'` + structured `validation_errors`. It stays queryable and counts toward reconciliation. **Invariant:** `raw_records == staging valid + staging quarantined` (no row vanishes).

### 5.5 Entity resolution & identity map (`resolution/`) → *no duplicates / single truth*
- `entity_identity_map(id, tenant_id, entity_type, source_system_id, source_id TEXT, canonical_id UUID, match_method ['deterministic','fuzzy','manual'], confidence NUMERIC, status ['auto_linked','pending_review','confirmed','rejected'], created_at)`; UNIQUE `(tenant_id, entity_type, source_system_id, source_id)`.
- Resolution order for a student row:
  1. **Existing source mapping?** `(source_system, source_id)` already in identity map → reuse its `canonical_id`. (This is what makes re-imports idempotent.)
  2. **Deterministic match:** within tenant, normalized `roll_no` matches an existing canonical student → link.
  3. **Fuzzy fallback:** score on `normalized_name + dob (+ email/phone)`. **High** confidence (≥ threshold) → auto-link. **Medium** → write `MergeReviewItem` (status `pending_review`), do **NOT** auto-merge. **Low** → treat as a new canonical student.
  4. Never auto-merge ambiguous matches — a wrong merge corrupts the SoT worse than a duplicate.
- `merge_review_items(... candidate_canonical_id, incoming_payload, score, status)` for human confirmation later (a Phase-2 UI; in Phase 1 just persist them).

### 5.6 LAYER 3 — CANONICAL upsert (`loading/canonical_loader.py`) → the SoT
- Canonical tables (all carry `tenant_id`, provenance, timestamps, soft-delete):
  `students, faculty, departments, programmes, courses, enrollment, attendance, internal_marks, semester_results, fees`. (`hostel, placement, research_publication` may be stubbed as empty tables for forward-compat — create them, don't populate yet.)
- **Natural keys for idempotent upsert (ON CONFLICT DO UPDATE):**
  - `students`: UNIQUE `(tenant_id, canonical_roll_no)`.
  - `attendance`: UNIQUE `(tenant_id, student_id, course_id, class_date, session_no)`.
  - `internal_marks`: UNIQUE `(tenant_id, student_id, course_id, assessment_type, attempt)`.
  - `fees`: UNIQUE `(tenant_id, student_id, term, fee_head)`.
  - `enrollment`: UNIQUE `(tenant_id, student_id, course_id, academic_year)`.
- **Transactional:** load per entity-type in a single transaction (or savepoints). Any failure rolls back that entity-type — **never** a half-loaded canonical state.
- **Provenance** written on every canonical row (`source_system_id`, `source_record_id`, `import_batch_id`, `ingested_at`).

### 5.7 Conflict resolution (`reconciliation/conflicts.py`) → *no silent inconsistency*
- When an upsert would change an existing canonical value (same natural key, different value from a different source/import):
  - Apply a **source-precedence policy** (`tenant`-configurable; default precedence order documented, e.g. ERP > Sheets > CSV upload).
  - Higher-precedence source wins; equal precedence + different value → **keep current, write a `data_conflicts` row, flag for review** — never silently clobber.
- `data_conflicts(id, tenant_id, table_name, record_id, field, existing_value, incoming_value, existing_source, incoming_source, import_batch_id, resolved BOOLEAN, at)`.

### 5.8 Reconciliation / data-quality report (`reconciliation/`)
At batch end produce a report (persist + expose via `imports.py`):
- counts: raw rows, valid, quarantined, inserted, updated, conflicts, review-queue items — **must reconcile** (raw = valid + quarantined; valid = inserted + updated + no-op).
- anomalies (`anomalies.py`): impossible marks, attendance > 100%, duplicate fee heads, out-of-range dates.
- completeness (`completeness.py`): % of expected fields populated per entity.
- This is the **pre-go-live data-quality report** and the seed of the future Data Quality Assistant module.

### 5.9 Proof-of-life read: Student 360 (`routes/students.py`)
`GET /students/{id}` returns the unified record assembled across canonical tables (profile + attendance summary + marks + fees), tenant-scoped. This proves the SoT works end to end and is the read path future features extend.

### 5.10 Phase 1 Definition of Done
Upload a real/realistic college CSV+Excel → raw landed (original retrievable) → mapped → cleaned/validated (bad rows quarantined) → entities resolved (no dupes) → canonical SoT populated (idempotent) → reconciliation report balances → Student 360 returns a unified student. All §9 acceptance tests pass.

---

## 6. Data dictionary — canonical core (minimum columns)

```sql
students(
  id uuid pk, tenant_id uuid not null,
  canonical_roll_no text not null,
  name text not null, dob date null, gender text null, category text null,
  email text null, phone text null,
  admission_year int null, programme_id uuid null references programmes(id),
  status text null,                      -- active/alumni/dropped/etc
  -- provenance + timestamps + soft delete via mixins
  unique (tenant_id, canonical_roll_no)
)
attendance(
  id uuid pk, tenant_id uuid not null,
  student_id uuid not null references students(id),
  course_id uuid not null references courses(id),
  class_date date not null, session_no int not null default 1,
  status text not null,                  -- present/absent/leave
  unique (tenant_id, student_id, course_id, class_date, session_no)
)
internal_marks(
  id uuid pk, tenant_id uuid not null,
  student_id uuid, course_id uuid,
  assessment_type text not null, attempt int not null default 1,
  max_marks numeric not null, obtained numeric not null,
  unique (tenant_id, student_id, course_id, assessment_type, attempt)
)
fees(
  id uuid pk, tenant_id uuid not null,
  student_id uuid, term text not null, fee_head text not null,
  amount_due numeric, amount_paid numeric, due_date date, paid_date date, status text,
  unique (tenant_id, student_id, term, fee_head)
)
-- programmes, departments, courses, enrollment, faculty: standard refs, all with tenant_id + provenance.
-- hostel, placement, research_publication: create empty (forward-compat), do not populate in Phase 1.
```
Implement these as SQLAlchemy 2.x mapped classes; generate Alembic migrations; add the RLS block (§4.3) to each.

---

## 7. API surface (Phase 0–1)

```
POST /auth/register            POST /auth/login            POST /auth/refresh
POST /sources                  GET  /sources
POST /mappings                 GET  /mappings              POST /mappings/suggest
POST /imports                  (multipart upload → creates ImportBatch, runs pipeline as background task)
GET  /imports/{id}             (status + reconciliation report)
GET  /imports/{id}/quarantine  (quarantined rows + reasons)
GET  /students/{id}            (Student 360)
GET  /health   /health/db
```
All routes except `/auth/*` and `/health*` require a valid JWT and run inside a tenant-scoped session.

---

## 8. How this aligns with what we build next (do not break these seams)

| Phase 0–1 choice | Future feature it enables |
|---|---|
| Canonical SoT tables, normalized | **Student Success Engine** (Phase 2) reads attendance/marks/fees directly |
| Provenance + audit log + evidence-ready facts | **Accreditation Assistant** DVV-grade evidence trail |
| `tenant_id` + RLS everywhere | Scale to **1000+ isolated colleges** |
| Governed, typed canonical fields | **NL query** runs over a semantic layer on clean data, never raw imports |
| `Connector` ABC (CSV first) | **ERPNext/Fedena API connectors** drop in behind the same pipeline |
| Reconciliation/anomaly outputs | **Data Quality Assistant** module |
| Batch state machine (in-process now) | Swap to a **queue/stream** later without changing stage logic |
| Soft delete + immutable raw | **DPDP** retention/erasure & recovery handled cleanly later (don't build consent now; leave the seam) |

---

## 9. Acceptance tests (the definition of done — implement these)

1. **Idempotent re-import:** import the same file twice → canonical row counts identical after the 2nd run; **zero duplicates**; identity map reused.
2. **Entity resolution:** (a) same `roll_no` across two files → **one** student; (b) same name, different roll → **two** students; (c) similar name + same dob, no roll → a `merge_review_item`, **not** an auto-merge.
3. **No data loss:** a file with malformed/garbage rows → those rows in `staging` as `quarantined` with reasons; **raw count = valid + quarantined**; original file retrievable from `raw_files`.
4. **Tenant isolation (RLS):** authenticated as tenant A, **no** endpoint ever returns tenant B data; a direct DB query with A's `app.current_tenant` set cannot read B's rows; with no tenant context set, protected tables return zero rows.
5. **Transactional load:** inject a failure mid-load → canonical tables show **no partial writes** for that batch; batch status `FAILED`.
6. **Conflict handling:** two sources give different values for the same canonical field → precedence applied **or** a `data_conflicts` row created; existing value never silently overwritten by a lower-precedence source.
7. **Provenance:** every canonical row resolves back to an `import_batch` and source record.
8. **Reconciliation balances:** the DQ report counts are internally consistent for every batch.

---

## 10. Explicitly OUT OF SCOPE for Phase 0–1 (do not build)
Student-risk logic/ML · NL query/LLM · accreditation drafting · API connectors for ERPNext/Fedena/closed systems · DPDP consent flows · SSO/MFA · notifications · dashboards/charts · the merge-review UI · queue/stream infra. Create forward-compat **table stubs** where noted (§6), but implement **no behaviour** for these. If asked to build any of them now, stop and confirm — they belong to later phases.
