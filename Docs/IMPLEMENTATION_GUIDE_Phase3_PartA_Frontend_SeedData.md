# IMPLEMENTATION GUIDE — Phase 3 Delivery
### PART A (backend endpoints) · PART B (wire the approved design to the API) · PART C (seed/test data)
### Contract style: build to this exactly.

---

## 0. Operating rules (READ FIRST)

1. This document is the contract. Do not invent endpoints, fields, or libraries not named here. If ambiguous, **stop and ask**.
2. **The mockup's scores are illustrative, not real.** The engine computes scores from rule weights (Phase 2 §6.1): a finding set of `ATTENDANCE_BELOW_THRESHOLD`(40)+`ACADEMIC_FAILING_INTERNALS`(35)+`ACADEMIC_DECLINE`(20) = **95**, not the mockup's 78. The frontend renders **engine-computed** scores/tiers. The seed data (PART C) is designed to produce the right **findings and tiers**, never to reproduce the mockup's exact numbers. Do not "fix" the engine to match the design.
3. **The frontend is never the security boundary.** Tenant + role scoping is enforced server-side (Phase 2). The UI reflects permissions; the API refuses data.
4. Backend changes go in the existing repo; reuse Phase 0–2 patterns (mixins, RLS, `risk_repository` scoping, audit, test fixtures). No new runtime deps for PART A.
5. Write tests as you build. Report the test summary and append a Phase 3 section to `CHANGELOG.md`.

---

# PART A — Backend additions (Claude Code, this repo)

Build these first so the frontend has a stable, typed API.

## A.1 CORS
Add CORS middleware to the FastAPI app. Allowed origins from a new env var `FRONTEND_ORIGINS` (comma-separated) in `core/config.py`; default `http://localhost:5173` (Vite dev). Do **not** combine `allow_origins=["*"]` with credentials. Allow credentials only if you adopt cookie-based refresh later.

## A.2 `GET /risk/summary`
Role-scoped via the **same** path `risk_repository` already uses (privileged → whole tenant; faculty → their `faculty_scopes`). Bulk aggregate queries only — no per-student loop. Response:
```json
{
  "total_assessed": 1240,
  "by_tier":      { "high": 86, "watch": 211, "low": 943 },
  "by_risk_type": { "attendance": 173, "academic": 142, "fee": 64 },
  "generated_at": "2026-06-24T10:00:00Z"
}
```
- `by_tier`: counts of **current** assessments (`is_current=true`) for visible students.
- `by_risk_type`: distinct visible students having ≥1 current finding of that type (a student may count under several types).

## A.3 `GET /risk/summary/by-department`
Same role-scoping. Response:
```json
{ "departments": [
  { "department": "CSE", "total": 320, "high": 28, "watch": 64, "low": 228 },
  { "department": "Unassigned", "total": 190, "high": 18, "watch": 40, "low": 132 }
] }
```
Department via the student→programme→department link; students with none resolvable → `"Unassigned"`. Bulk aggregate.

## A.4 Trends — DEFERRED (do NOT build now)
The mockup's "Risk trend over time" needs historical weekly tier counts, which no endpoint serves and which a new pilot has no data for yet. **Do not build `GET /risk/trends` in this pass.** The frontend shows a placeholder (PART B). If/when wanted later, it's a point-in-time reconstruction over `risk_assessments.computed_at` history — a separate, tested task.

## A.5 PART A acceptance tests (`tests/test_risk_summary.py`)
1. `summary` tier/type counts correct for a seeded dataset.
2. **Role scoping (the one that matters):** a faculty user's `summary` + `by-department` reflect only their `faculty_scopes`; a privileged user sees the whole tenant.
3. Tenant isolation: tenant A's summary never includes tenant B; `test_rls_coverage.py` unaffected (no new tables).
4. `by-department` groups correctly incl. the `"Unassigned"` bucket.
5. No-N+1: a bounded query count regardless of student count.

---

# PART B — Wire the approved design to the API

Realize the approved design (`Risk Copilot.dc.html`: Institution overview + Student 360, plus the Risk Board and the empty/error/stale states) as the React app specified in `IMPLEMENTATION_SPEC_Phase3.md` PART B (stack, auth, routing, states, a11y — follow it). This section pins the **data bindings and the design-specific rules** that came out of the design review.

## B.1 Screen → endpoint binding (use exactly these; all but summary already exist)
| Screen / element | Endpoint(s) | Notes |
|---|---|---|
| **Faculty Risk Board** | `GET /risk/students?tier=&risk_type=&min_score=&page=` | Role-scoped server-side. Default filter shows **watch + high only** (low isn't "at risk"). |
| **Student 360** (whole screen) | `GET /students/{id}` + `GET /risk/students/{id}` | Profile from the first; tier/score, **findings (with evidence)**, **history timeline**, **interventions** from the second. **No new endpoint needed — the history timeline is already in `/risk/students/{id}`.** |
| **Dashboard tiles + distribution bar** | `GET /risk/summary` | PART A. |
| **Dashboard "By department"** | `GET /risk/summary/by-department` | PART A. Compute the high-share % client-side (`high/total`). |
| **Dashboard "Highest risk right now"** | `GET /risk/students?tier=high` (top N) | Already exists. |
| **Dashboard "Risk trend over time"** | — none — | **Render a placeholder**: "Trend builds as risk data accumulates." Do not fake it; do not call a non-existent endpoint. |
| **Intervention create/update/outcome** | `POST/PATCH /risk/interventions`, `POST …/{id}/outcome` | Invalidate the board + 360 queries on success. |
| **Risk config** | `GET/PUT /risk/config` | Client validation mirrors `RiskConfigModel`; server is authority (handle 422). |
| **Imports + recompute status** | `GET /imports`, `GET /imports/{id}` | Surface `risk_recompute_status`; offer `POST /risk/recompute` when not `ok`. |
| **Alerts** | `GET /risk/alerts`, `PATCH /risk/alerts/{id}/read` | Unread count in nav. |

## B.2 Render engine values, not mockup values
Bind score/tier/findings to the API response. The mockup's 78/60/55 are placeholders; show whatever `/risk/students` returns. Tier drives colour+label+shape (the design's square/diamond/circle) — keep that, it's the colour-vision-safe treatment.

## B.3 Role-gate the Dashboard (the prototype shows a mentor on it — don't replicate)
The "Institution overview" is **privileged-only** (principal/registrar/management/admin). A `faculty` user:
- does not see the Dashboard nav item and cannot route to it (UX guard), **and**
- if they call `/risk/summary` directly, the server returns **their scope only** (already true via A.2's role-scoping — verify).
A mentor like Dr. Iyer lands on the **Risk Board**, not the institution view.

## B.4 The "NO MENTOR" tag
The `"Unassigned"` department bucket means *no department resolved* — that is **not** the same as *no mentor*. Either relabel that tag to "No department" / "Unassigned", or, only if you want a true no-mentor signal, derive it from `faculty_scopes` coverage. Don't let the label assert something the data doesn't.

## B.5 Minor consent gate (carry Phase 2 §9 into the UI)
The board seed includes minors (Ananya, Diya). Show the **minor badge** on the board row and the 360. When creating a `parent_contact` intervention for a `minor`/`unknown` student, require an explicit consent confirmation in the UI and send `guardian_consent_confirmed=true`; the server enforces it (403 without). Non-parent interventions are unrestricted. This is an acceptance test.

## B.6 Stale-data note
If the latest import's `risk_recompute_status` is `partial`/`failed`, show the calm, non-blocking note (it's a designed state) linking to `/imports` with a re-run action.

## B.7 PART B acceptance (per `IMPLEMENTATION_SPEC_Phase3.md` §B.10)
Auth/401→refresh→logout; role-aware nav; **minor consent gate**; loading/empty/error states on board, dashboard, 360; `tsc --noEmit` clean with API types generated from the OpenAPI schema. (Recommended Playwright e2e: login → board → open 360 → log a non-parent intervention → see it reflected.)

---

# PART C — Seed / test data

Goal: one command populates a realistic demo tenant so (a) the frontend renders real engine output and (b) the system is exercised end to end. Deliver a **seed script** plus **sample CSVs** for the ingestion path.

## C.1 `scripts/seed_demo.py` (build this)
Idempotent (safe to re-run; skip/upsert if the demo tenant exists). It must:
1. Create tenant **"Demo Engineering College"** (slug `demo-eng`).
2. Create users (argon2 passwords; print credentials at the end):
   - `principal@demo-eng.edu` — role `principal` (to view the Dashboard).
   - `meera.iyer@demo-eng.edu` — role `faculty`, with a `faculty_scope` of `department=CSE` (Dr. Meera Iyer, the mentor).
   - `admin@demo-eng.edu` — role `admin`.
3. Create departments **CSE, MECH, ECE, CIVIL**; programme **B.Tech Computer Science** (+ minimal programmes for the others); CSE courses **DBMS, OS, CN, TOC**.
4. Create the **named CSE cohort** (Dr. Iyer's scope) with the signals in C.2, plus filler (C.3) and other-department students (C.4).
5. Write canonical rows directly (dev seed — set tenant context, set provenance `source_system='seed'`, respect RLS). Set `internal_marks.assessment_date` so academic ordering is correct.
6. Call `recompute_for_tenant(...)` so assessments + findings + alerts are generated.
7. Print: login credentials, tenant id, and the resulting tier counts so the operator can sanity-check.

> This seeds via the canonical layer for speed/determinism (it bypasses ingestion + entity resolution on purpose). To exercise the **ingestion** path, use the CSVs in C.5 through the import API.

## C.2 Named CSE cohort — signals and EXPECTED findings (engine computes the score/tier)

> Values chosen with clear margins to trigger exactly the intended rules. **Expected tier is what the engine produces** under default weights — note it differs from the mockup's illustrative tiers/scores.

| roll | name | dob (age) | attendance | internals (assessment_date asc) | fees | → expected findings | → engine tier (score) |
|---|---|---|---|---|---|---|---|
| 21CSE045 | Aarav Sharma | 2003-04-12 (adult) | 60% over ~100 sessions | 70, 36, 32 | current | BELOW_THRESHOLD + FAILING(2) + DECLINE | **high (95)** |
| 21CSE009 | Mohammed Faiz | 2003-01-20 (adult) | 78% over ~50 (no att. finding) | 33, 35 | overdue 41d | FAILING(2) + FEE_OVERDUE | **high (50)** |
| 21CSE112 | Sneha Reddy | 2003-08-30 (adult) | overall 77%, but recent-12 window 64% vs prior-12 84% (≥24 sessions) | 66, 47 | DECLINING + DECLINE | **watch (40)** |
| 21CSE077 | Ananya Nair | 2008-10-12 (**minor**, 17) | 71% over ~30 | 58, 55 | BELOW_THRESHOLD | **watch (40)** |
| 21CSE058 | Diya Patel | 2008-12-01 (**minor**, 17) | 70% over ~30 | 72, 70 | BELOW_THRESHOLD | **watch (40)** |
| 21CSE131 | Rohit Verma | 2003-06-05 (adult) | 80% over ~50 | 61, 44 | DECLINE only (61→44, drop 17; 44 not <40) | **low (20)** → *excluded from board* |
| 21CSE200 | Karthik Menon | 2003-03-03 (adult) | 95% over ~50 | 75, 78 | FEE_OVERDUE only | **low (15)** → *excluded from board* |

This set covers **all five rules**, yields high/watch/low, includes **two minors** (badge + consent-gate testing), and includes two deliberate **low** cases (a decline-only and a fee-only) that prove the board's "watch+high only" default exclusion. (Realism note: a 17-year-old in 3rd year is demographically unusual; acceptable for exercising the minor gate, or move the minors to a 1st-year programme if you prefer realism over design parity.)

Attendance generation: for a target overall pct P over N sessions, distribute present/absent across the CSE courses and across dated sessions. For the **declining** cases (Sneha, and optionally make trend visible), order session dates so the most recent `attendance_trend_window` (12) sessions sit at the lower pct and the prior 12 at the higher pct.

## C.3 Filler CSE students (so the board denominator is realistic)
~17 additional CSE students with **clean records** (attendance ≥85%, internals ≥55%, fees current) → **no findings → low → not on the board**. Realistic Indian names, roll numbers `21CSE0xx`. This makes "X of ~24 flagged" believable and gives the 360/summary real volume.

## C.4 Other-department students (so the Dashboard is non-trivial)
Lightweight: ~40 students across MECH/ECE/CIVIL and ~15 **Unassigned** (no department), with a sprinkling of findings (mostly low, a few watch/high) so `by-department` and the tiles show a real spread. Exact counts don't need to match the mockup — the Dashboard renders whatever the engine produces.

## C.5 Sample CSVs for the ingestion path (`scripts/sample_data/`)
Provide small, real-format files so the **import API** path can be tested manually (create source → create column mapping → upload → recompute). Use these exact shapes (headers are examples the column-mapping maps to canonical fields):

`students.csv`
```
Roll No,Full Name,DOB,Gender,Email,Phone,Admission Year,Department,Programme
21CSE045,Aarav Sharma,12/04/2003,M,aarav.sharma@demo-eng.edu,9876500045,2021,CSE,B.Tech Computer Science
21CSE077,Ananya Nair,12/10/2008,F,ananya.nair@demo-eng.edu,9876500077,2021,CSE,B.Tech Computer Science
```
`attendance.csv`
```
Roll No,Course Code,Date,Status
21CSE045,DBMS,2026-01-12,present
21CSE045,DBMS,2026-01-14,absent
21CSE077,DBMS,2026-01-12,present
```
`internal_marks.csv`
```
Roll No,Course Code,Assessment,Assessment Date,Max Marks,Obtained
21CSE045,DBMS,CT1,2026-02-10,100,70
21CSE045,DBMS,CT2,2026-03-15,100,36
21CSE045,DBMS,CT3,2026-04-20,100,32
```
`fees.csv`
```
Roll No,Term,Fee Head,Amount Due,Amount Paid,Due Date,Paid Date
21CSE009,2025-S1,Tuition,60000,40000,2026-05-10,
```
> Map "Assessment Date" → `internal_marks.assessment_date` so academic decline orders correctly (Phase 2 hardening Part 1). Leaving it unmapped is allowed (falls back to `created_at`) but then bulk imports won't order reliably.

## C.6 Run + verify
`python -m scripts.seed_demo` → prints credentials + tier counts. Then: log in as `meera.iyer@demo-eng.edu` → Board shows the watch+high CSE students (Aarav, Mohammed Faiz, Sneha, Ananya, Diya), **not** Rohit or Karthik (low). Log in as `principal@demo-eng.edu` → Dashboard shows tiles + by-department + highest-risk. Open Aarav's 360 → 3 findings with evidence + the worsening history + the completed mentor-meeting intervention. Add a `parent_contact` for Ananya → consent gate appears.

---

## Final report (return this)
- PART A: `pytest` summary; the summary-endpoint tests pass (esp. role scoping); `test_rls_coverage.py` unaffected.
- PART B: `tsc --noEmit` clean; the §B.7 tests pass; confirm the Dashboard is role-gated and the trend placeholder is shown (no fake data).
- PART C: `scripts/seed_demo.py` runs idempotently and prints the tier counts; sample CSVs import cleanly through the API.
- Any decision made where this doc was silent (documented), and a Phase 3 section appended to `CHANGELOG.md`.
- Confirm: no new backend runtime deps; backend changes limited to PART A + the seed script.
