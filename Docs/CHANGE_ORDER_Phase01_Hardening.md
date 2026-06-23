# CHANGE ORDER — Phase 0/1 Hardening
### Apply to the AI-ERP-Copilot backend. Contract style: do exactly this, no more.

---

## 0. Operating rules (READ FIRST)

1. Apply **only** the changes in this document. Do **not** refactor, rename, or "improve" code outside these changes — the rest of Phase 0/1 passed review and must not regress.
2. If any instruction here conflicts with the current code in a way you didn't expect, **stop and report** what you found instead of guessing.
3. Do **not** add new dependencies. Everything here uses what's already installed (FastAPI, SQLAlchemy, pytest, psycopg).
4. After applying, run the **full** suite (`pytest`) and report: how many passed/failed, and the names of any failures. The existing tests (34) must still pass — call out any regression explicitly.
5. Keep each change in its own commit, message referencing the change number below.

---

## CHANGE 1 — FIX: audit actor + log tenant context on pipeline-loaded data (real bug)

**Problem.** `run_pipeline` runs as a background task and writes canonical rows (students, attendance, …), but it never sets `actor_user_id_ctx` or `tenant_id_ctx`. So the audit-log rows for ingested data get a stale/empty `actor_user_id`, and log lines during ingestion show the wrong `tenant_id`. This breaks the audit trail's actor attribution.

### 1a. Pass the uploading user into the pipeline

**File:** `app/api/routes/imports.py` — in `create_import`, the background task currently is:

```python
background_tasks.add_task(run_pipeline, current_user.tenant_id, batch.id, content)
```

Change it to also pass the user id:

```python
background_tasks.add_task(run_pipeline, current_user.tenant_id, batch.id, content, current_user.user_id)
```

### 1b. Accept it and set the context vars at the top of the pipeline

**File:** `app/services/ingestion/pipeline.py`

- Add the parameter to `run_pipeline`. Current signature is `run_pipeline(tenant_id, import_batch_id, content)`; change to:
  ```python
  def run_pipeline(tenant_id: UUID, import_batch_id: UUID, content: bytes, actor_user_id: UUID) -> None:
  ```
- Add these imports at the top of the file (if not already present):
  ```python
  from app.core.audit import actor_user_id_ctx
  from app.core.logging import tenant_id_ctx
  ```
- As the **very first statements inside `run_pipeline`**, before opening any session or calling any `_phase_*` function:
  ```python
  actor_user_id_ctx.set(str(actor_user_id))
  tenant_id_ctx.set(str(tenant_id))
  ```
- **Do NOT add a reset** of these contextvars (set-without-reset is the existing, deliberate pattern — see `api/deps.py`; the next pipeline run sets fresh values, and resetting risks the cross-thread `Token` error documented in CHANGELOG.md decision #9).

### 1c. Test — pipeline-loaded row has the correct audit actor

**File:** `tests/test_ingestion_pipeline.py` — add:

```python
def test_pipeline_loaded_row_has_correct_audit_actor(client, superuser_connection):
    slug = "audit-actor-college"
    token = _register(client, slug)
    source_id = _create_source(client, token)
    _create_mapping(client, token, source_id, "student", STUDENT_MAPPING)

    admin_user_id = superuser_connection.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": f"admin@{slug}.edu"}
    ).scalar_one()

    content = (STUDENT_CSV_HEADER + "CS101,John Doe,12/05/2003,M,john@test.edu,9876543210,2021\n").encode()
    batch_id = _upload(client, token, source_id, "student", "students.csv", content)
    assert _get_batch(client, token, batch_id)["status"] == "COMPLETED"

    student_id = superuser_connection.execute(
        text("SELECT id FROM students WHERE canonical_roll_no = 'CS101'")
    ).scalar_one()

    actor = superuser_connection.execute(
        text(
            "SELECT actor_user_id FROM audit_log "
            "WHERE table_name = 'students' AND record_id = :rid AND action = 'insert'"
        ),
        {"rid": str(student_id)},
    ).scalar_one()
    assert str(actor) == str(admin_user_id), "pipeline-loaded canonical row must record the importing user as audit actor"
```

> If `audit_log.record_id` or `actor_user_id` is typed such that the comparison needs casting, mirror whatever the existing `test_rls_isolation.py` audit assertions do — do not change the audit schema.

**Acceptance:** this test passes; the audit row for the ingested student carries the real importer's id, not `-`/null/stale.

---

## CHANGE 2 — HARDENING: RLS-coverage meta-test (defense in depth, primary)

**Why.** The real latent isolation risk isn't a forgotten `WHERE tenant_id` (RLS `FORCE` already backstops that) — it's a **future migration adding a tenant table and forgetting the RLS block** (spec §4.3). This test makes that impossible to ship silently.

**File:** `tests/test_rls_coverage.py` (new):

```python
from sqlalchemy import text

# Tables intentionally exempt from RLS, each with a written justification.
# Empty by default. Do NOT add to this to silence a failure without a real reason —
# a failure here usually means a table is missing its RLS block (spec §4.3).
EXEMPT_TABLES: dict[str, str] = {
    # "some_table": "reason it legitimately has no tenant scoping",
}


def test_every_tenant_table_has_rls_enabled_forced_and_policy(superuser_connection):
    tenant_tables = [
        r[0]
        for r in superuser_connection.execute(
            text(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE c.relkind = 'r'
                  AND n.nspname = 'public'
                  AND a.attname = 'tenant_id'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            )
        ).all()
    ]
    assert tenant_tables, "expected at least one tenant-scoped table — schema not migrated?"

    failures = []
    for table in tenant_tables:
        if table in EXEMPT_TABLES:
            continue
        sec = superuser_connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :t"
            ),
            {"t": table},
        ).one()
        policy_count = superuser_connection.execute(
            text("SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = :t"),
            {"t": table},
        ).scalar_one()
        if not sec.relrowsecurity:
            failures.append(f"{table}: RLS not ENABLED")
        if not sec.relforcerowsecurity:
            failures.append(f"{table}: RLS not FORCED")
        if policy_count == 0:
            failures.append(f"{table}: no RLS policy present")

    assert not failures, "RLS coverage gaps (spec §4.3):\n" + "\n".join(failures)
```

**Acceptance:** test passes. **If it fails**, for each listed table either (a) add the missing `ENABLE/FORCE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation` block in a **new** Alembic migration (matching spec §4.3 exactly), or (b) if a table legitimately needs no tenant scoping, add it to `EXEMPT_TABLES` with a one-line justification. **Report which path you took for each.** Do not blanket-exempt to make it green.

---

## CHANGE 3 — TEST: explicit re-import idempotency (different bytes, same rows)

**Why.** The existing idempotency test re-uploads an *identical* file, so it short-circuits at the content-hash check. This proves the **loader** itself is idempotent when the pipeline actually re-runs on the same logical rows from a different file.

**File:** `tests/test_ingestion_pipeline.py` — add:

```python
def test_reimport_different_bytes_same_rows_no_new_canonical(client, superuser_connection):
    token, source_id = _setup_student_import(client, "reimport-college")

    file1 = (STUDENT_CSV_HEADER + "CS101,John Doe,12/05/2003,M,john@test.edu,9876543210,2021\n").encode()
    # Same logical row + an extra UNMAPPED column => different bytes (hash differs, pipeline re-runs)
    # but identical mapped/canonical data.
    file2 = (
        STUDENT_CSV_HEADER.rstrip("\n") + ",Notes\n"
        + "CS101,John Doe,12/05/2003,M,john@test.edu,9876543210,2021,ignore-me\n"
    ).encode()

    b1 = _upload(client, token, source_id, "student", "f1.csv", file1)
    assert _get_batch(client, token, b1)["status"] == "COMPLETED"

    b2 = _upload(client, token, source_id, "student", "f2.csv", file2)
    assert b2 != b1, "different bytes must NOT be hash-deduped — the pipeline must actually re-run"
    assert _get_batch(client, token, b2)["status"] == "COMPLETED"

    student_count = superuser_connection.execute(
        text("SELECT count(*) FROM students WHERE canonical_roll_no = 'CS101'")
    ).scalar_one()
    assert student_count == 1, "row-level upsert must update in place, not duplicate"

    link_count = superuser_connection.execute(
        text(
            "SELECT count(*) FROM entity_identity_map "
            "WHERE entity_type = 'student' AND source_id = 'CS101'"
        )
    ).scalar_one()
    assert link_count == 1, "identity map must be reused, not re-created"
```

**Acceptance:** test passes. If `link_count` comes back as 2, the resolver is writing a duplicate identity link on re-resolve — fix the resolver to reuse the existing `(source_system, source_id)` link before re-matching, and report it.

---

## CHANGE 4 — TEST: prove the resolver's no-roll-no path is unreachable

**Why.** The resolver only writes a fuzzy identity link `if roll_no:`. That's correct *only if* a student row without a roll number can never reach the loader. This test proves the validator quarantines it first.

**File:** `tests/test_ingestion_pipeline.py` — add:

```python
def test_student_missing_roll_no_is_quarantined(client, superuser_connection):
    token, source_id = _setup_student_import(client, "noroll-college")
    content = (STUDENT_CSV_HEADER + ",No Roll Student,01/01/2003,M,noroll@test.edu,9000000010,2021\n").encode()

    batch_id = _upload(client, token, source_id, "student", "f.csv", content)
    body = _get_batch(client, token, batch_id)
    assert body["row_count_quarantined"] == 1
    assert body["row_count_loaded"] == 0

    count = superuser_connection.execute(text("SELECT count(*) FROM students")).scalar_one()
    assert count == 0
```

**Acceptance:** test passes (row is quarantined, no student created). **If it fails** (the row loaded), the student validator is missing a required-field rule for `canonical_roll_no` — add it in `app/services/ingestion/cleaning/validators.py` so a missing/empty roll number quarantines the row with reason `"missing required field: canonical_roll_no"`, then re-run. Report which case you hit.

---

## 5. Final acceptance (report all of this back)

- [ ] Change 1 applied (imports.py + pipeline.py edits) and `test_pipeline_loaded_row_has_correct_audit_actor` passes.
- [ ] `tests/test_rls_coverage.py` passes (and, if it initially failed, a report of which tables were fixed vs exempted and why).
- [ ] `test_reimport_different_bytes_same_rows_no_new_canonical` passes.
- [ ] `test_student_missing_roll_no_is_quarantined` passes.
- [ ] **Full suite green with no regressions** — report the final passed/failed count (was 34; should now be 38, unless a meta-test surfaced a real gap, in which case report it).
- [ ] No new dependencies added; no files changed outside those named above (plus a possible new Alembic migration if Change 2 surfaced a missing RLS block).
```

Don't change anything else. When done, paste the final `pytest` summary line and the resolution of any meta-test gap.
