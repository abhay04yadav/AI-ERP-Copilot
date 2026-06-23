# IMPLEMENTATION SPEC — Phase 2
### Student Success Engine (rules-based, production-grade) for the AI College Copilot
### This document is the contract. Build to it exactly.

---

## 0. How to use this document (READ FIRST — instructions for the AI coding agent)

You are implementing **Phase 2: the Student Success Engine** — the deterministic, explainable risk-detection layer that reads the canonical Single-Source-of-Truth built in Phase 0/1 and produces, for every student, a risk tier with human-readable reasons, an intervention workflow, and alerts.

Obey these rules for the entire build:

1. **This document is the single source of truth.** Do **not** invent tables, columns, endpoints, libraries, thresholds, or folder names not specified here. If something is ambiguous or missing, **stop and ask** — never guess, never "fill in."
2. **Do not add any new dependency.** The whole engine is pure Python + the existing stack (FastAPI, SQLAlchemy 2.x, Alembic, pytest). If you believe you need a new library, **stop and ask** — you almost certainly don't.
3. **Reuse Phase 0/1, do not reinvent it.** Use the existing mixins (`PKMixin`, `TenantMixin`, `TimestampMixin`, `SoftDeleteMixin`), `core/rls.py::set_tenant_context`, `core/audit.py::register_audit_hooks`, the repository/schema/service/route layering, the `get_tenant_session` dependency, and the test fixtures (`client`, `superuser_connection`, `app_session_factory`). New code must look like it was written by the same author as Phase 1.
4. **Every new tenant table gets the RLS block** (`ENABLE` + `FORCE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation`) in its Alembic migration, exactly as Phase 1 did, and must pass the existing `tests/test_rls_coverage.py` meta-test with `EXEMPT_TABLES` empty.
5. **All schema changes go through one new Alembic migration** (`down_revision` = the Phase 1 migration). Never edit a migration that has run.
6. **Write the tests in §13 as you build** — they are the definition of done. A step is not complete until its tests pass. Report the `pytest` summary at the end and any deviation.
7. **The engine is ADVISORY ONLY.** It never takes an automated adverse action against a student (no auto-debarment, no auto-anything). It computes, explains, alerts a human, and logs. This is a hard rule, not a preference (see §9, DPDP).
8. **Determinism is mandatory.** Given the same canonical inputs and the same config, the engine must produce byte-identical assessments. No randomness, no wall-clock-dependent logic inside scoring (timestamps are metadata only, never inputs to the score).
9. Commit in small, reviewable units following the **build order in §12** — one step per commit, message referencing the step.
10. When you finish a step, **report which acceptance tests pass** before moving on.

---

## 1. What we are building & first principles

**The Student Success Engine** turns the canonical data (attendance, internal marks, fees) into a per-student **RiskAssessment**: an overall score (0–100), a tier (`low` / `watch` / `high`), and a set of **findings** — each a typed, human-readable reason backed by the exact numbers that triggered it. It maintains an **intervention** workflow (suggest → assign → act → record outcome) and emits **alerts**. It recomputes automatically when new data is imported and on demand.

**Non-negotiable principles (apply everywhere):**
- **Explainable, never a black box.** No score without findings. Every finding carries its evidence (the actual percentages/counts and the threshold it crossed). A `low` tier means zero findings.
- **Rules first, ML-ready.** Phase 2 ships a deterministic **rules** evaluator. The evaluator sits behind an interface (`RiskEvaluator`) so an `MLRiskEvaluator` can be added later **without touching callers, storage, or the API**. Every assessment stores a **`signals_snapshot`** so future ML can train on the same inputs.
- **Configuration, not hardcoding.** Every threshold, weight, and tier cutoff lives in a per-tenant `risk_configs` row. No magic numbers in code — only named defaults that seed the config.
- **Versioned & idempotent.** Every assessment stamps `model_version` + `config_version`. Recompute is idempotent: identical inputs ⇒ no new assessment row (the current one stands); changed inputs ⇒ supersede + insert.
- **Advisory + human-in-the-loop + DPDP-aware.** No automated adverse action. Minor (under-18) handling is built in from day one (§9).
- **Tenant- and role-scoped.** RLS is the floor; the API additionally scopes by role (faculty see only their assigned cohort).
- **Production performance.** Batch recompute uses **bulk aggregate queries** — never N+1 per student.

---

## 2. Tech stack (locked — no additions)

Same as Phase 0/1: Python 3.12+, FastAPI, SQLAlchemy 2.x (typed mapped classes), Alembic, PostgreSQL 16+, Pydantic v2, pytest. **Zero new dependencies.** Age/date math uses the stdlib `datetime`/`date`. The rules engine is pure Python.

---

## 3. Repository structure (add exactly this — do not restructure existing code)

```
backend/app/
  models/
    risk.py                # RiskConfig, RiskAssessment, RiskFinding,
                           #   Intervention, InterventionOutcome, RiskAlert, FacultyScope
  schemas/
    risk.py                # Pydantic DTOs (request/response only)
  repositories/
    risk_repository.py     # tenant-scoped reads: at-risk list, assessment+findings, history
  services/
    risk/
      __init__.py
      config.py            # DEFAULT_RISK_CONFIG, get_or_seed_config(), config loader
      engine.py            # orchestrator: recompute_for_student / _for_students /
                           #   _for_tenant / _for_import_batch  + idempotent persist
      scoring.py           # aggregate findings -> score; score -> tier (from config)
      scoping.py           # resolve a user's visible student_ids by role + FacultyScope
      interventions.py     # intervention lifecycle service (suggest/assign/complete/outcome)
      alerts.py            # alert generation (in-app) + minor/consent gating
      signals/
        __init__.py
        base.py            # StudentSignals dataclass (the engine's typed input)
        attendance.py      # bulk attendance signal computation (one query set per tenant)
        academic.py        # bulk academic signal computation
        fees.py            # bulk fee-delay signal computation
      rules/
        base.py            # Rule protocol; RiskFinding dataclass; RiskType / Severity enums
        attendance_rules.py
        academic_rules.py
        fee_rules.py
        registry.py        # ordered list of active rules (the rule set v1)
      evaluator/
        base.py            # RiskEvaluator ABC + AssessmentResult dataclass
        rules_evaluator.py # RulesRiskEvaluator (Phase 2 implementation)
        # ml_evaluator.py  -> FUTURE, DO NOT BUILD
  api/routes/
    risk.py                # all /risk endpoints
backend/migrations/versions/
    <new>_phase2_risk_engine.py
backend/tests/
    test_risk_signals.py
    test_risk_rules.py
    test_risk_scoring.py
    test_risk_engine.py        # determinism, idempotency, recompute-on-import
    test_risk_api.py           # role scoping, tenant isolation, endpoints
    test_risk_minor_handling.py
    test_risk_interventions.py
```

---

## 4. Data model (new tables — all `tenant_id` + RLS + audit where mutable)

Implement as SQLAlchemy 2.x mapped classes reusing the existing mixins; generate **one** Alembic migration; add every table to the RLS block and to `register_audit_hooks` where noted.

### 4.1 `risk_configs` — per-tenant thresholds (versioned)
```
risk_configs(
  id uuid pk, tenant_id uuid not null,
  version int not null,                 -- monotonically increasing per tenant
  is_active bool not null default true, -- exactly one active per tenant
  config jsonb not null,                -- the full threshold/weight/cutoff object (§6.1)
  created_at timestamptz not null default now(),
  created_by uuid null,                 -- user who changed it (null = system seed)
  partial unique (tenant_id) where is_active   -- one active config per tenant
)
```
Mixins: `PKMixin`, `TenantMixin`. Audit: **yes** (config changes are security-relevant).

### 4.2 `risk_assessments` — one current per student, full history retained
```
risk_assessments(
  id uuid pk, tenant_id uuid not null,
  student_id uuid not null references students(id),
  is_current bool not null default true,
  model_type text not null,             -- 'rules' (CHECK in ('rules','ml'))
  model_version text not null,          -- e.g. 'rules-v1'
  config_version int not null,
  overall_score numeric(5,2) not null,  -- 0.00–100.00
  tier text not null,                   -- CHECK in ('low','watch','high')
  subject_minor_status text not null,   -- CHECK in ('minor','adult','unknown')  (§9)
  signals_snapshot jsonb not null,      -- the exact StudentSignals used (explainability + future ML)
  triggered_by text not null,           -- CHECK in ('import','manual','scheduled')
  triggered_by_import_batch_id uuid null references import_batches(id),
  computed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  partial unique (tenant_id, student_id) where is_current,  -- one current per student
  index (tenant_id, is_current, tier),
  index (tenant_id, is_current, overall_score)
)
```
Mixins: `PKMixin`, `TenantMixin`. Audit: **yes**.

### 4.3 `risk_findings` — the reasons behind an assessment
```
risk_findings(
  id uuid pk, tenant_id uuid not null,
  assessment_id uuid not null references risk_assessments(id) on delete cascade,
  risk_type text not null,              -- CHECK in ('attendance','academic','fee')
  code text not null,                   -- e.g. 'ATTENDANCE_BELOW_THRESHOLD' (stable machine code)
  severity text not null,               -- CHECK in ('low','medium','high')
  weight_contribution numeric(5,2) not null,  -- points this finding added to the score
  message text not null,                -- human-readable, e.g. "Attendance 61% in DBMS (below 75%)"
  evidence jsonb not null,              -- the numbers: {scope, value, threshold, ...}
  index (tenant_id, assessment_id),
  index (tenant_id, risk_type)
)
```
Mixins: `PKMixin`, `TenantMixin`. Audit: no (immutable child of an audited parent; cascade-deleted only when a superseded assessment is pruned, which we do **not** do in Phase 2 — see note).
> **Note:** Phase 2 never deletes assessments or findings; `on delete cascade` is defensive only. History is retained for accreditation/ML.

### 4.4 `interventions` — the action loop
```
interventions(
  id uuid pk, tenant_id uuid not null,
  student_id uuid not null references students(id),
  source_assessment_id uuid null references risk_assessments(id),  -- what prompted it
  type text not null,                   -- CHECK in ('mentor_meeting','remedial_class','parent_contact','counselling','other')
  status text not null,                 -- CHECK in ('suggested','open','in_progress','completed','dismissed')
  title text not null,
  notes text null,
  assigned_to uuid null references users(id),   -- a faculty/mentor user
  created_by uuid null references users(id),
  is_deleted bool not null default false, deleted_at timestamptz null,
  created_at timestamptz not null default now(), updated_at timestamptz not null,
  index (tenant_id, student_id, status),
  index (tenant_id, assigned_to, status)
)
```
Mixins: `PKMixin`, `TenantMixin`, `TimestampMixin`, `SoftDeleteMixin`. Audit: **yes**.

### 4.5 `intervention_outcomes` — closing the loop (future ML labels)
```
intervention_outcomes(
  id uuid pk, tenant_id uuid not null,
  intervention_id uuid not null references interventions(id),
  outcome text not null,                -- CHECK in ('improved','no_change','worsened','unknown')
  notes text null,
  recorded_by uuid null references users(id),
  recorded_at timestamptz not null default now()
)
```
Mixins: `PKMixin`, `TenantMixin`. Audit: **yes**.

### 4.6 `risk_alerts` — generated notifications (in-app for Phase 2)
```
risk_alerts(
  id uuid pk, tenant_id uuid not null,
  student_id uuid not null references students(id),
  assessment_id uuid null references risk_assessments(id),
  recipient_user_id uuid null references users(id),  -- resolved recipient (a faculty/principal user)
  channel text not null default 'in_app',  -- CHECK in ('in_app','email')  (email = stub in Phase 2)
  status text not null default 'pending',  -- CHECK in ('pending','sent','read','suppressed')
  reason text not null,                 -- why this alert fired (e.g. 'tier_escalated_to_high')
  payload jsonb not null,
  created_at timestamptz not null default now(), sent_at timestamptz null,
  index (tenant_id, recipient_user_id, status)
)
```
Mixins: `PKMixin`, `TenantMixin`. Audit: no (high-volume, not security-critical; status changes logged via app logging).

### 4.7 `faculty_scopes` — what a faculty user is allowed to see
```
faculty_scopes(
  id uuid pk, tenant_id uuid not null,
  user_id uuid not null references users(id),
  scope_type text not null,             -- CHECK in ('department','programme','course','section')
  scope_ref text not null,              -- the code/section value (e.g. department code 'CSE')
  created_by uuid null,
  created_at timestamptz not null default now(),
  unique (tenant_id, user_id, scope_type, scope_ref)
)
```
Mixins: `PKMixin`, `TenantMixin`. Audit: **yes** (access-control data).

---

## 5. Signals layer (`services/risk/signals/`) — the typed engine input

Signals are **computed in bulk per tenant** (one set of aggregate queries), then assembled per student into a `StudentSignals` dataclass. **No per-student DB round-trips in batch recompute.**

### 5.1 `StudentSignals` (`signals/base.py`)
A frozen dataclass — the complete, serializable input to the evaluator:
```python
@dataclass(frozen=True)
class CourseAttendance:
    course_code: str
    course_name: str
    present: int
    total: int
    pct: float | None            # None when total == 0

@dataclass(frozen=True)
class StudentSignals:
    student_id: UUID
    dob: date | None
    # attendance
    overall_attendance_pct: float | None
    overall_sessions: int
    attendance_by_course: tuple[CourseAttendance, ...]
    attendance_recent_pct: float | None   # last N sessions window
    attendance_prior_pct: float | None    # the window before that (for trend)
    # academic
    latest_internal_pct_by_course: tuple[tuple[str, float], ...]   # (course_code, pct)
    failing_internal_count: int
    academic_latest_pct: float | None     # most recent internal overall
    academic_baseline_pct: float | None   # mean of that student's prior internals
    # fees
    max_fee_overdue_days: int             # 0 if none overdue
```
> The snapshot persisted on the assessment is the JSON form of this object. It is the contract future ML trains on — keep it stable and additive.

### 5.2 Computation rules
- **Attendance** (`attendance.py`): aggregate `attendance` rows per (student, course) into present/total and pct; overall = sum across courses. Trend windows: `attendance_recent_pct` = pct over the most recent `attendance_trend_window` sessions (config), `attendance_prior_pct` = the window immediately before. Use SQL aggregation (`GROUP BY`), not Python loops over raw rows.
- **Academic** (`academic.py`): per student, order internal_marks by a stable key (term/assessment order); `latest_internal_pct` = obtained/max of the most recent; `academic_baseline_pct` = mean pct of all prior internals; `failing_internal_count` = count of internals with pct < `academic_fail_pct`.
- **Fees** (`fees.py`): `max_fee_overdue_days` = max(today − due_date) over unpaid/partially-paid fees where due_date < today; else 0.
- All queries are tenant-scoped (RLS + explicit `tenant_id` filter) and restricted to non-soft-deleted students.

---

## 6. Rules layer (`services/risk/rules/`) — deterministic, pure, unit-tested

### 6.1 The default config (seed into `risk_configs.config`; all thresholds live here)
```json
{
  "attendance_threshold_pct": 75,
  "attendance_min_sessions": 10,
  "attendance_trend_window": 12,
  "attendance_decline_points": 15,
  "academic_fail_pct": 40,
  "academic_decline_points": 15,
  "fee_overdue_days": 30,
  "weights": {
    "ATTENDANCE_BELOW_THRESHOLD": 40,
    "ATTENDANCE_DECLINING": 20,
    "ACADEMIC_FAILING_INTERNALS": 35,
    "ACADEMIC_DECLINE": 20,
    "FEE_OVERDUE": 15
  },
  "tier_cutoffs": { "watch": 25, "high": 50 }
}
```

### 6.2 Rule contract (`rules/base.py`)
```python
class RiskType(str, Enum): ATTENDANCE="attendance"; ACADEMIC="academic"; FEE="fee"
class Severity(str, Enum): LOW="low"; MEDIUM="medium"; HIGH="high"

@dataclass(frozen=True)
class RiskFinding:
    risk_type: RiskType
    code: str
    severity: Severity
    weight_contribution: float
    message: str
    evidence: dict

class Rule(Protocol):
    code: str
    def evaluate(self, signals: StudentSignals, config: dict) -> RiskFinding | None: ...
```
Rules are **pure** (no I/O, no DB, no clock). Each returns `None` or exactly one `RiskFinding`. Contribution = the configured weight (fixed, not magnitude-scaled — magnitude lives in `evidence`). Each rule is unit-tested in isolation.

### 6.3 The rule set v1 (`rules/registry.py` lists them in this order)
| code | type | triggers when | severity | message shape |
|---|---|---|---|---|
| `ATTENDANCE_BELOW_THRESHOLD` | attendance | `overall_attendance_pct < attendance_threshold_pct` **and** `overall_sessions >= attendance_min_sessions` | high | "Attendance {pct}% (below {threshold}%)" |
| `ATTENDANCE_DECLINING` | attendance | `attendance_prior_pct − attendance_recent_pct >= attendance_decline_points` (both present) | medium | "Attendance fell {drop} pts ({prior}%→{recent}%)" |
| `ACADEMIC_FAILING_INTERNALS` | academic | `failing_internal_count >= 1` | high | "{n} internal(s) below {fail_pct}%" |
| `ACADEMIC_DECLINE` | academic | `academic_baseline_pct − academic_latest_pct >= academic_decline_points` (both present) | medium | "Latest internal {latest}% vs baseline {baseline}%" |
| `FEE_OVERDUE` | fee | `max_fee_overdue_days >= fee_overdue_days` | low | "Fees overdue {days} days" |

> **Confidence guard:** the attendance-below rule must not fire on tiny samples (`attendance_min_sessions`) — this prevents false flags early in a term. Bake this in; it is part of correctness, tested in §13.

---

## 7. Scoring & tiering (`services/risk/scoring.py`)
- `overall_score = min(100, sum(finding.weight_contribution for finding in findings))`. Deterministic, explainable, reconciles exactly with the findings.
- `tier`: `high` if `score >= tier_cutoffs.high`, else `watch` if `score >= tier_cutoffs.watch`, else `low`.
- **Invariant (test it):** `findings == [] ⟺ tier == 'low'` and `score == 0`.

---

## 8. Evaluator (`services/risk/evaluator/`) — the future-proof seam

```python
@dataclass(frozen=True)
class AssessmentResult:
    overall_score: float
    tier: str
    findings: list[RiskFinding]
    model_type: str          # 'rules'
    model_version: str       # 'rules-v1'

class RiskEvaluator(ABC):
    @abstractmethod
    def evaluate(self, signals: StudentSignals, config: dict) -> AssessmentResult: ...
```
`RulesRiskEvaluator` runs every rule in `registry`, collects findings, calls `scoring`, returns an `AssessmentResult` stamped `model_type='rules'`, `model_version='rules-v1'`. **The engine, storage, and API depend only on `RiskEvaluator` + `AssessmentResult`** — so a future `MLRiskEvaluator` (different `model_type`/`model_version`, same output shape) is a drop-in with zero changes to callers. **Do not build the ML evaluator now.**

---

## 9. DPDP / minor handling (build in from day one — not optional)

A "child" under the DPDP Act is anyone **under 18**; many first-years are 17. The engine therefore:
- Computes `subject_minor_status` from `student.dob` at `computed_at`: `minor` (age < 18), `adult` (age ≥ 18), `unknown` (dob null). Store it on every assessment.
- Uses **only academic/administrative signals** (attendance, marks, fees) — never behavioural/engagement tracking — which keeps risk processing within "legitimate educational processing" for minors. Do not add behavioural signals in Phase 2.
- Is **advisory only**: no automated adverse action anywhere, for anyone (hard rule §0.7).
- **Gates `parent_contact` interventions for minors and unknown-dob students:** the engine/`alerts` service must **never auto-create, auto-suggest, or auto-send** a `parent_contact` intervention or a parent-directed alert for a `minor`/`unknown` subject. A human may still create one manually, but the API must require an explicit `guardian_consent_confirmed=true` flag on that request and record who confirmed it. Non-parent interventions (mentor_meeting, remedial_class, counselling) are unrestricted.
- All assessments and interventions are audited (actor via the existing `actor_user_id_ctx`).
> Add a code comment at each gate pointing to this section. A legal review precedes any change that would make minor-profiling non-advisory.

---

## 10. The engine & recompute (`services/risk/engine.py`)

### 10.1 Entry points
```python
def recompute_for_students(session, tenant_id, student_ids, *, triggered_by, import_batch_id=None) -> RecomputeSummary
def recompute_for_tenant(session, tenant_id, *, triggered_by) -> RecomputeSummary       # all active students
def recompute_for_import_batch(session, tenant_id, import_batch_id) -> RecomputeSummary  # affected students only
```
- `recompute_for_import_batch` derives affected `student_ids` from the batch's `staging_records.resolved_entity_id` for risk-relevant entity types (`student`, `attendance`, `internal_mark`, `fee`, `enrollment`) and delegates to `recompute_for_students`.
- `RecomputeSummary` = `{evaluated, changed, unchanged, skipped, errors:[...]}` — returned and logged.

### 10.2 Algorithm (idempotent, bulk, isolated)
1. Load the active `risk_config` for the tenant (seed default if none).
2. **Bulk-compute signals** for all target students (the §5 aggregate queries) → `dict[student_id, StudentSignals]`. No per-student queries.
3. For each student: `result = evaluator.evaluate(signals, config)`.
4. **Idempotent persist:** compare `result` to the student's current assessment (same tier, same score, same finding codes+contributions). If **unchanged**, do nothing (the current assessment stands). If **changed** (or none exists): in one transaction, set the old current `is_current=false`, insert the new assessment (`is_current=true`) + its findings, stamp `model_version`/`config_version`/`triggered_by`/`subject_minor_status`/`signals_snapshot`, and (per §11) generate alerts for material escalations.
5. **Isolation:** a failure evaluating/persisting one student is caught, recorded in `summary.errors`, and does **not** abort the others. (Mirrors Phase 1's per-row quarantine philosophy.)
6. Set tenant context (`set_tenant_context`) at the start of each transaction; honour RLS.

### 10.3 Wiring to Phase 1 (one line, no coupling the other way)
In `services/ingestion/pipeline.py::run_pipeline`, **after** `_phase_reconcile` succeeds (batch `COMPLETED`), call:
```python
from app.services.risk.engine import recompute_for_import_batch
recompute_for_import_batch(session_or_new_session, tenant_id, import_batch_id)
```
Run it in its own transaction/session after the import transaction commits, inside the same background task (so `actor_user_id_ctx`/`tenant_id_ctx`, already set per Phase-0/1 CHANGE 1, attribute the assessments to the importing user). A failure here must **not** flip the import to `FAILED` (the import already succeeded) — log it and record it; the import stays `COMPLETED`. The risk module imports nothing from the pipeline; the pipeline calls one risk entry point. Keep the dependency one-directional.

---

## 11. Alerts (`services/risk/alerts.py`)
- On persist, generate a `risk_alert` only for **material change**: a student newly entering `high`, or escalating `watch→high`. (No alert for unchanged or de-escalation in Phase 2.)
- Recipient resolution: the student's in-scope faculty (via `faculty_scopes`) and tenant principals/registrars. **Apply §9 minor gating** — never a parent-directed alert for a minor/unknown subject automatically.
- Channel `in_app` only in Phase 2 (`email` is a stubbed no-op that marks `status='pending'`; do not integrate an email provider now).

---

## 12. Build order (do in this sequence, one commit per step)

1. **Models + migration.** All §4 tables as mapped classes; one Alembic migration with the RLS block on every new table; register audit hooks on `risk_configs`, `risk_assessments`, `interventions`, `intervention_outcomes`, `faculty_scopes`. Run `test_rls_coverage.py` — must stay green.
2. **Config.** `DEFAULT_RISK_CONFIG` (§6.1) + `get_or_seed_config()`. Seed an active config on first use per tenant.
3. **Signals.** The three bulk signal computers + `StudentSignals`. Unit tests (`test_risk_signals.py`).
4. **Rules + scoring + evaluator.** Pure rule functions, `registry`, `scoring`, `RulesRiskEvaluator`. Unit tests (`test_risk_rules.py`, `test_risk_scoring.py`) — including the confidence guard and the `findings==[] ⟺ tier=='low'` invariant.
5. **Engine.** `recompute_for_students/_for_tenant/_for_import_batch` with bulk signals + idempotent persist + per-student isolation. Tests (`test_risk_engine.py`): determinism, idempotency (no new row when unchanged), recompute-on-change, error isolation.
6. **Minor handling.** `subject_minor_status` computation + parent-contact/alert gating. Tests (`test_risk_minor_handling.py`).
7. **Pipeline wiring.** The §10.3 hook; integration test: import attendance → engine runs → at-risk reflects it; import failure path unaffected.
8. **Interventions + alerts services.** Lifecycle + outcome + in-app alerts with minor gating. Tests (`test_risk_interventions.py`).
9. **Scoping + repository + API.** `faculty_scopes` resolution, `risk_repository`, all `/risk` endpoints with role scoping. Tests (`test_risk_api.py`): tenant isolation, faculty-only-their-cohort, principal-all.
10. **Final pass.** Full `pytest`; report summary + any deviation.

---

## 13. API surface (Phase 2)
```
GET   /risk/students                 # at-risk list; query: tier?, risk_type?, department?, min_score?, page; role-scoped; sorted score desc
GET   /risk/students/{student_id}    # current assessment + findings + history + active interventions
POST  /risk/recompute                # body: {scope:'tenant'|'students', student_ids?}; admin/registrar; returns RecomputeSummary
GET   /risk/config                   # active config (admin)
PUT   /risk/config                   # update thresholds -> new version; admin; recompute NOT auto-triggered (caller may call /recompute)
POST  /risk/interventions            # create (manual); parent_contact for minor requires guardian_consent_confirmed=true (§9)
GET   /risk/interventions            # filter: student_id?, status?, assigned_to?; role-scoped
PATCH /risk/interventions/{id}       # status/assignment/notes transitions
POST  /risk/interventions/{id}/outcome   # record outcome
GET   /risk/alerts                   # current user's alerts; query: status?
PATCH /risk/alerts/{id}/read         # mark read
```
- All routes require a valid JWT and a tenant-scoped session. **Role scoping (server-side, never from client input):** `admin/principal/registrar/management` → all tenant students; `faculty` → only students within their `faculty_scopes`; `student` role → **out of scope for Phase 2** (return 403). A faculty request for a student outside scope returns 404 (not 403 — don't reveal existence).
- Reads go through `risk_repository` (tenant-scoped + role-scoped). Writes go through the services.

---

## 14. Production code-quality standards (enforce all)
- **Typing:** full type hints on every function/method; mapped classes typed (SQLAlchemy 2.x `Mapped[...]`). Code should be mypy-clean under the repo's config.
- **Purity & determinism:** rule functions and scoring are pure and clock-independent; the only non-determinism allowed is `computed_at`/`created_at` metadata, never an input to score/tier.
- **No magic numbers:** every threshold/weight/cutoff comes from config; named constants only for the default seed.
- **Explainability invariant:** never persist a non-`low` assessment without findings; never persist a score that doesn't equal the clamped sum of its findings. Assert in code.
- **Idempotency & versioning:** stamp `model_version` + `config_version` on every assessment; recompute writes nothing when unchanged.
- **Performance:** batch recompute issues a **bounded** number of queries independent of student count (bulk aggregates). No N+1 — enforced by a query-count test (§15).
- **Transactions & isolation:** per-student persist is atomic; one bad student never aborts the batch; tenant context set inside every transaction.
- **Security:** RLS on all new tables; explicit tenant filter in every repository query (defense in depth); role scoping server-side; audit hooks on the mutable/security-relevant tables; never trust `student_id`/scope from the client beyond what role scoping permits.
- **Error handling:** typed exceptions + the existing handlers; recompute records per-student errors in the summary rather than failing silently or globally.
- **Observability:** structured logs with `tenant_id`, `student_id`, `model_version`, and `RecomputeSummary` counts.
- **Consistency:** match Phase 0/1 naming, layering, docstring style, and the "decisions where the spec was silent" CHANGELOG discipline. Append a Phase 2 section to `CHANGELOG.md`.
- **Docstrings:** every module/public function documents its purpose and cites the spec section it implements (e.g. "spec §6.3").

---

## 15. Acceptance tests (the definition of done — implement all)
1. **Signals:** bulk computation returns correct attendance pct/sessions, trend windows, latest-vs-baseline marks, failing count, and max overdue days for a seeded dataset.
2. **Each rule in isolation:** fires exactly when its condition holds and not otherwise; `ATTENDANCE_BELOW_THRESHOLD` does **not** fire below `attendance_min_sessions`.
3. **Scoring/tiering:** a known finding set yields the exact score and tier; `findings==[] ⟹ score==0 and tier=='low'`.
4. **Determinism:** evaluating the same `StudentSignals` + config twice yields identical `AssessmentResult`.
5. **Idempotent recompute:** recompute twice on unchanged data ⟹ **no new assessment row** (one `is_current` per student); changed data ⟹ old superseded (`is_current=false`) + one new current; history retained.
6. **Recompute on import:** importing attendance that drops a student below threshold ⟹ that student appears in `GET /risk/students` as `high` with an `ATTENDANCE_BELOW_THRESHOLD` finding; an import failure leaves risk state untouched and the import still behaves per Phase 1.
7. **Error isolation:** one student raising during evaluation is recorded in `summary.errors`; all other students are still assessed.
8. **Tenant isolation:** tenant A users never see tenant B assessments/interventions/alerts via any endpoint or direct RLS query; `test_rls_coverage.py` stays green with the new tables and `EXEMPT_TABLES` empty.
9. **Role scoping:** a faculty user sees only students within their `faculty_scopes`; a principal sees all; a faculty request for an out-of-scope `student_id` returns 404; `student` role is 403.
10. **Minor handling:** a student with age < 18 ⟹ `subject_minor_status='minor'`; the engine/alerts never auto-create a `parent_contact` intervention or parent-directed alert for them; a manual `parent_contact` for a minor without `guardian_consent_confirmed=true` is rejected; with it, accepted and the confirmer recorded.
11. **Intervention lifecycle:** suggested → assigned → in_progress → completed → outcome recorded; each write audited with the correct actor.
12. **Config effect:** lowering `attendance_threshold_pct` and recomputing changes which students flag, deterministically.
13. **No N+1:** recomputing for N students issues a query count that does **not** scale with N (assert with a query counter / SQLAlchemy event listener).
14. **Audit:** assessment and intervention writes produce `audit_log` rows with the correct `actor_user_id` (the recompute trigger's user / the API caller).

---

## 16. Explicitly OUT OF SCOPE for Phase 2 (do not build — stop and confirm if asked)
ML risk models / `MLRiskEvaluator` · dropout-risk and placement-risk models · behavioural/engagement signals · NL query over risk data · accreditation use of risk data · real email/SMS/WhatsApp delivery (in-app alert records only) · the student self-service view · scheduled/cron recompute infra (on-import + manual only) · dashboards/charts (Phase 3 UI) · the merge-review UI. Leave the seams (evaluator interface, signals snapshot, alert channels) so these are additive later — but implement **no behaviour** for them now.
```
```

---

## 17. Final report (return this)
- `pytest` summary line; confirmation all §15 tests pass and `test_rls_coverage.py` stays green.
- A new **Phase 2 section appended to `CHANGELOG.md`** listing: what was built, any "decisions made where the spec was silent" (reasoned, not guessed), and any deviation with its justification.
- Confirmation: no new dependencies; no changes outside the files named here plus the one-line pipeline hook and the audit-hook registrations.
