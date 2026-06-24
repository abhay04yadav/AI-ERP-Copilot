# CHANGE ORDER — Phase 2 Hardening, Part 2
### Apply to the AI-ERP-Copilot backend. Contract style: do exactly this, no more.

---

## 0. Operating rules (READ FIRST)

1. Apply **only** the change below. Do not refactor anything else — the full suite is **101 passing** and must stay green plus the new test(s) here.
2. If this conflicts with what you find in the code (e.g. a legitimate case where `student_id` or `course_id` is null on a canonical row), **stop and report it** — do not guess, do not silently work around it.
3. No new dependencies. One new Alembic migration, `down_revision` = current head.
4. One commit. Report the `pytest` summary and any deviation when done.

---

## CHANGE 1 — FIX: enforce `NOT NULL` on `internal_marks.student_id`/`course_id` and `fees.student_id`

**Problem.** Both tables have nullable `student_id`/`course_id` (written that way in the original Phase 2 spec, §6, with no `NOT NULL`). Postgres treats every `NULL` as distinct in a unique constraint, so the natural-key uniqueness on these tables (`uq_internal_marks_natural_key`, `uq_fees_natural_key`) does **not** actually prevent duplicates for any row where `student_id` (or `course_id`) is null. This is a real gap in the dedup guarantee, not a cosmetic issue.

### 1a. Confirm the assumption before changing anything
Before writing the migration, check whether any row in `internal_marks` or `fees` (across all tenants/environments you can inspect, including test fixtures) currently has a null `student_id` or `course_id`. Also check the loader path (`canonical_loader.py::upsert_internal_mark`, `upsert_fee`) and the entity-resolution flow: can a mark/fee row reach canonical at all without a resolved student? If you find a legitimate path where it can (e.g. a fee charged at a programme level with no individual student), **stop and report it** instead of proceeding — that's a real design question, not something to paper over with a migration.

If, as expected, no such row exists and the loader always requires a resolved `student_id` before upserting (course_id may legitimately be more often present, confirm both), proceed.

### 1b. Migration
```sql
ALTER TABLE internal_marks ALTER COLUMN student_id SET NOT NULL;
ALTER TABLE internal_marks ALTER COLUMN course_id SET NOT NULL;
ALTER TABLE fees ALTER COLUMN student_id SET NOT NULL;
```
Downgrade: `ALTER COLUMN ... DROP NOT NULL` for all three. If `fees.course_id` doesn't exist (fees may not be course-scoped per the canonical model — check), don't invent it; only touch the columns named above that actually exist.

> If the migration fails because rows with nulls already exist (in any environment you can check), **stop and report** — do not delete or backfill data to force it through.

### 1c. Models
`app/models/canonical.py`:
- `InternalMark.student_id`, `InternalMark.course_id`: change `Mapped[uuid.UUID | None]` → `Mapped[uuid.UUID]`, drop `nullable=True`.
- `Fee.student_id`: same change.
- Remove or update the existing code comment on these fields that explains the current nullable-FK quirk (it documented the gap this change closes — update it to say the constraint is now enforced, or delete it if it no longer applies).

### 1d. Validators / loader (confirm, don't necessarily change)
Check `services/ingestion/cleaning/validators.py` for `internal_mark` and `fee`: a row with an unresolved student should already be quarantined before reaching the loader (per Phase 1's entity-resolution flow). If that's already true, no validator change is needed — the DB constraint becomes a backstop, not the primary defense. If it's *not* already true (a row could currently slip through with a null student reference), add the required-field check so it quarantines with a clear reason rather than failing at the DB layer with a raw constraint-violation error.

### 1e. Tests
- `tests/test_risk_*` / `tests/test_ingestion_pipeline.py` (wherever fits the existing layout): add a test that attempting to construct/upsert an `InternalMark` or `Fee` with `student_id=None` raises (either quarantined earlier in the pipeline with a clear reason, or a DB `IntegrityError` if exercised below the validator) — pick whichever reflects where the original spec's defense-in-depth actually sits, and assert that, not both.
- Confirm (re-run) the existing acceptance test suite that already covers unresolved-reference quarantine (Phase 1 spec §15 / "unresolved-reference quarantine") still passes — this change should make that guarantee *stronger*, not change its observed behaviour for valid imports.

---

## 1. Final report (return this)
- `pytest` summary line; confirm 101 (or 101 + however many new tests you added) pass; `test_rls_coverage.py` unaffected (no RLS change here).
- What you found in step 1a (no nulls existed / loader already prevents it — or the opposite, reported instead of worked around).
- Confirm: no new dependencies; changes confined to the migration, `canonical.py`, and (if needed) `validators.py` + the new test(s).
- A short note appended to `CHANGELOG.md` under "Phase 2 hardening, part 2."
