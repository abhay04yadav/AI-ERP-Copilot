# CHANGE ORDER — Phase 2 Hardening
### Apply to the AI-ERP-Copilot backend. Contract style: do exactly this, no more.

---

## 0. Operating rules (READ FIRST)

1. Apply **only** the changes in this document. Do **not** refactor or "improve" anything outside them — Phase 0/1/2 passed review and must not regress. The full suite is **89 passing**; it must stay green (plus the new tests below).
2. If an instruction conflicts with the current code in a way you didn't expect, **stop and report** — do not guess.
3. **Backward compatibility is mandatory.** Every change here is additive/optional. Existing imports, configs, API responses, and all 89 tests must behave identically unless a test is explicitly about the new behaviour.
4. **No new runtime dependencies.** CHANGE 4 adds *dev-only* tooling (mypy, ruff) — that is the single allowed exception and is called out explicitly; do not add anything else.
5. All schema changes go in **one new Alembic migration**, `down_revision` = current head. No RLS policy changes are needed (both tables touched already have RLS; no new tables) — confirm `tests/test_rls_coverage.py` stays green.
6. Write the tests in each change as you go. One commit per change, message referencing the change number.
7. CHANGES are independent — they may be applied and committed separately. If you do a subset, say which.
8. When done, report the `pytest` summary and any deviation.

---

## CHANGE 1 — FIX: give the academic-decline signal a trustworthy time axis

**Problem.** `ACADEMIC_DECLINE` compares a student's latest internal mark to their baseline, but `services/risk/signals/academic.py` orders `internal_marks` by `(created_at, id)`. For a college that **bulk-imports** a term's marks in one file, `created_at` ≈ import time, not the real assessment order — so "latest vs baseline" can be wrong. `internal_marks` has no assessment date/sequence column. Add an **optional** one and order by it when present, falling back to current behaviour when absent (so nothing regresses).

### 1a. Schema (in the single new migration)
Add a nullable column to the existing `internal_marks` table:
```sql
ALTER TABLE internal_marks ADD COLUMN assessment_date DATE NULL;
```
Nullable, no backfill, no RLS change (table already has RLS). Add the downgrade (`DROP COLUMN`).

### 1b. Model
`app/models/canonical.py` (`InternalMark`): add `assessment_date: Mapped[date | None] = mapped_column(Date, nullable=True)`. Import `date`/`Date` as the file already does for other date columns.

### 1c. Ingestion (keep it OPTIONAL end-to-end)
Wire `assessment_date` as an **optional** canonical field for `entity_type='internal_mark'`:
- Allow it as a mapping target (so a college *may* map a "Assessment Date" header to it; colleges that don't, leave it null).
- In the `internal_mark` cleaning/normalization path, parse it with the **existing date normalizer** used elsewhere (handle `dd/mm/yyyy`, `dd-mm-yy`, Excel serials, blanks → null). Do **not** add it to the required-field validators — it stays optional.
- In `services/ingestion/loading/canonical_loader.py::upsert_internal_mark`, set `assessment_date` from the cleaned payload when present (treat absent/blank as `None`).

### 1d. Signal ordering (the actual fix)
In `services/risk/signals/academic.py`, replace the ordering key `(created_at, id)` with an **effective assessment date** that prefers `assessment_date` and falls back to `created_at`:
```
effective = COALESCE(internal_marks.assessment_date, internal_marks.created_at::date)
ORDER BY effective ASC, internal_marks.created_at ASC, internal_marks.id ASC
```
- "Latest internal" = the row with the greatest `effective` (tiebreak `created_at`, then `id`).
- "Baseline" = mean pct of the remaining (earlier) internals, exactly as today.
- When no row has `assessment_date` (the current real-world case), `effective` collapses to `created_at::date` and ordering is unchanged — **no regression**.

### 1e. Tests (`tests/test_risk_signals.py`)
- `test_academic_ordering_uses_assessment_date_when_present`: seed three internals for one student with `created_at` in one order but `assessment_date` in the **opposite** order; assert `academic_latest_pct` is the one with the latest `assessment_date` (not the latest `created_at`), and baseline is the mean of the other two.
- `test_academic_ordering_falls_back_to_created_at_when_no_assessment_date`: with all `assessment_date` null, behaviour matches the pre-change result (latest = greatest `created_at`).
- An ingestion test: import an `internal_mark` file **with** an assessment-date column mapped → the column lands on the canonical rows; import **without** it → rows load fine with `assessment_date` null.

**Acceptance:** the dated-ordering test passes; the no-date path is byte-identical to before; all 89 existing tests still pass.

> Interim option if you defer 1a–1d: none required — but until this ships, treat `ACADEMIC_DECLINE` as provisional and rely on `ACADEMIC_FAILING_INTERNALS` (absolute marks, ordering-independent) as the trustworthy academic signal. Note this in the CHANGELOG.

---

## CHANGE 2 — HARDENING: validate the risk config on `PUT /risk/config`

**Problem.** A malformed admin config update (missing key, bad cutoffs) can poison every later recompute with a `KeyError` deep in scoring. Validate the shape on the write path.

### 2a. Schema model (`app/schemas/risk.py`)
Add a Pydantic v2 model that mirrors `DEFAULT_RISK_CONFIG` (spec §6.1), with `model_config = ConfigDict(extra="forbid")` so typos are rejected, not silently ignored:
```python
class RiskWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ATTENDANCE_BELOW_THRESHOLD: float = Field(ge=0)
    ATTENDANCE_DECLINING: float = Field(ge=0)
    ACADEMIC_FAILING_INTERNALS: float = Field(ge=0)
    ACADEMIC_DECLINE: float = Field(ge=0)
    FEE_OVERDUE: float = Field(ge=0)

class TierCutoffs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    watch: float = Field(ge=0, le=100)
    high: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _watch_below_high(self):
        if self.watch >= self.high:
            raise ValueError("tier_cutoffs.watch must be strictly less than high")
        return self

class RiskConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attendance_threshold_pct: float = Field(ge=0, le=100)
    attendance_min_sessions: int = Field(ge=0)
    attendance_trend_window: int = Field(ge=1)
    attendance_decline_points: float = Field(ge=0, le=100)
    academic_fail_pct: float = Field(ge=0, le=100)
    academic_decline_points: float = Field(ge=0, le=100)
    fee_overdue_days: int = Field(ge=0)
    weights: RiskWeights
    tier_cutoffs: TierCutoffs
```

### 2b. Enforce on the write path
In `app/api/routes/risk.py::PUT /risk/config`, validate the incoming `config` through `RiskConfigModel` **before** calling `set_new_config`. On `ValidationError`, return **422** with the error detail (let FastAPI's handler render it, or raise the repo's existing validation exception). Store the validated, normalized dict (`model.model_dump()`).

### 2c. Tests (`tests/test_risk_api.py`)
- `test_put_config_rejects_missing_key` → 422, active config unchanged.
- `test_put_config_rejects_watch_ge_high` → 422.
- `test_put_config_rejects_unknown_key` (typo) → 422.
- `test_put_config_accepts_valid_update` → 200, new version active.
- `test_default_config_is_valid` (in `tests/test_risk_scoring.py` or config test): `RiskConfigModel(**DEFAULT_RISK_CONFIG)` constructs without error — guarantees the shipped default always satisfies its own schema.

**Acceptance:** all five pass; a bad config can no longer reach `set_new_config`.

> Note: `weights` is intentionally coupled to rule-set v1's five codes. When a future rule is added, this model must be updated alongside it — add a one-line CHANGELOG note to that effect.

---

## CHANGE 3 — HARDENING: make a failed post-import recompute observable

**Problem.** After an import, `run_pipeline` calls `recompute_for_import_batch` and only logs the `RecomputeSummary`. If recompute partially fails (or the worker dies mid-run), the import still reads `COMPLETED` and nobody knows risk is stale.

### 3a. Schema (same new migration as CHANGE 1)
Add to `import_batches`:
```sql
ALTER TABLE import_batches ADD COLUMN risk_recompute_status text NULL;   -- 'ok' | 'partial' | 'failed' | 'skipped'
ALTER TABLE import_batches ADD COLUMN risk_recompute_summary jsonb NULL;
```
Add a `CHECK` constraint on the status values (matching the Phase 1 style of `CHECK ... IN (...)`), allowing NULL. Downgrade drops both. No RLS change.

### 3b. Model + response schema
- `app/models/ingestion.py` (`ImportBatch`): add the two columns (`risk_recompute_status: Mapped[str | None]`, `risk_recompute_summary: Mapped[dict | None]`).
- `app/schemas/imports.py` (`ImportBatchResponse`): expose both fields.

### 3c. Set them after the post-import recompute (`services/ingestion/pipeline.py`)
Where `run_pipeline` calls `recompute_for_import_batch` after `_phase_reconcile` succeeds, wrap it so the outcome is persisted and **never flips the import to FAILED** (the import already succeeded):
```python
try:
    summary = recompute_for_import_batch(session, tenant_id, import_batch_id)
    status = "partial" if summary.errors else "ok"
    summary_json = summary_to_dict(summary)   # {evaluated, changed, unchanged, skipped, errors}
except Exception as exc:                       # recompute failure must not fail the import
    logger.exception("Post-import risk recompute failed for import_batch_id=%s", import_batch_id)
    status, summary_json = "failed", {"error": str(exc)}
# persist on the batch in its own short transaction (set tenant context first)
_set_recompute_outcome(tenant_id, import_batch_id, status, summary_json)
```
Implement `_set_recompute_outcome` in the same module (opens a session, `set_tenant_context`, updates the batch row, commits). Keep the dependency one-directional (pipeline calls risk; risk does not import the pipeline).

### 3d. Tests (`tests/test_risk_engine.py`)
- `test_import_records_recompute_status_ok`: a clean import → `GET /imports/{id}` shows `risk_recompute_status == 'ok'` and a summary with `evaluated >= 1`.
- `test_import_recompute_failure_marks_partial_or_failed_but_import_stays_completed`: force a recompute error for one student (monkeypatch the evaluator to raise for a specific student) → batch status stays `COMPLETED`, `risk_recompute_status` is `'partial'` (per-student isolation) and the failing student is listed in the summary errors.

**Acceptance:** both pass; a silent stale-risk state is now visible via the import status.

---

## CHANGE 4 — TOOLING: add mypy + ruff to CI  *(dev-dependencies — confirm before adding)*

**Why.** All new code is fully typed but nothing enforces it. Locking in type-checking + linting turns that discipline into a guarantee for Phase 3+.

> ⚠️ This adds **dev-only** dependencies (`mypy`, `ruff`). Per rule 4, confirm this is wanted before proceeding. If not, skip CHANGE 4 entirely.

### 4a. Dev dependencies + config (`pyproject.toml`)
- Add `mypy` and `ruff` to a dev/optional dependency group (match the repo's existing grouping convention).
- Add a pragmatic config — **not** `--strict` initially:
  ```toml
  [tool.mypy]
  python_version = "3.12"
  plugins = []
  ignore_missing_imports = true   # third-party stubs absent; revisit per-package later
  warn_unused_ignores = true
  disallow_untyped_defs = true
  check_untyped_defs = true
  [tool.ruff]
  line-length = 120
  target-version = "py312"
  [tool.ruff.lint]
  select = ["E", "F", "I", "B", "UP"]
  ```

### 4b. Make them pass on the current code — do NOT mass-suppress
- Run `ruff check` and `mypy app` against the existing tree.
- **If a large number of pre-existing errors surface in Phase 0/1/2 code, STOP and report the count and the top categories** rather than blanket-adding `# type: ignore` / `# noqa`. We decide together whether to fix, narrow the config, or scope mypy to new modules first. Only fix clear real issues and add **targeted, commented** ignores where a third-party stub is genuinely missing.

### 4c. CI workflow (`.github/workflows/ci.yml`)
Add (or extend an existing) workflow that runs, on push/PR: `ruff check`, `mypy app`, then `pytest`. The test job needs Docker available for testcontainers (GitHub-hosted runners provide it) and whatever env the suite already requires (e.g. `APP_DB_PASSWORD`) — **match how the tests are run today**; if the existing local test command sets env/services, mirror that, and if anything about the test env is unclear, stop and ask rather than guessing secrets.

**Acceptance:** `ruff check` and `mypy app` exit clean (or the pre-existing-error report from 4b is delivered); `pytest` runs in CI; no runtime dependency added.

---

## 5. Final report (return this)
- `pytest` summary line; confirm the original 89 still pass plus the new tests; `tests/test_rls_coverage.py` still green (`EXEMPT_TABLES` empty).
- Which CHANGES were applied (all, or a subset), each as its own commit.
- For CHANGE 1: confirm the no-`assessment_date` path is unchanged from before.
- For CHANGE 4 (if attempted): the clean result, or the pre-existing-error report from 4b — **not** a wall of suppressions.
- A new **"Phase 2 hardening" section appended to `CHANGELOG.md`** documenting each change and any decision made where this doc was silent.
- Confirm: no new *runtime* dependencies; no changes outside the files named here plus the one new migration.
```

Apply CHANGES 2 and 3 first if you want the quickest wins; CHANGE 1 is the higher-value correctness fix but the larger one; CHANGE 4 only if you want the tooling now.
