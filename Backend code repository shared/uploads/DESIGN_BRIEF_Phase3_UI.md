# DESIGN BRIEF — AI College Copilot (Phase 3 UI)
### For generating the Faculty Risk Board + Student 360 (and the dashboard system that inherits from them)
### Goal: distinctive, realistic, production-credible screens grounded in what the backend actually returns.

---

## 0. How to use this brief

Generate **static, high-fidelity design mockups** — not wired-up code — for the two screens in §6, using the **real data shapes** in §3 and the **real seed content** in §4. Do not use lorem ipsum, placeholder boxes, or invented fields. Every label, number, and message on screen must be something the backend in §3 could actually produce. If you need a field that isn't in §3, stop — it doesn't exist; design with what's there.

Resolve the visual identity yourself within the direction in §5, then design. Show the happy path **and** the empty and error states (§7) — a real tool is judged on those.

---

## 1. What this product is (one paragraph)

An AI copilot for Indian colleges that sits **on top of** the college's existing systems (it is not an ERP). It reads attendance, internal marks, and fees, and surfaces — for every student — a **risk tier with the specific reasons behind it**, so faculty mentors and college leadership can intervene early. The screens we're designing are where that intelligence becomes visible and actionable. The audience is **busy administrators and faculty mentors** who open this daily to act on student welfare — not a consumer audience. The single job of the primary screen: *let someone glance and immediately know who needs help and why.*

---

## 2. Who uses these screens

- **Faculty / Mentor** — sees only **their assigned cohort** (their sections/courses). Their home screen is the **Risk Board**: "who in my group is at risk, and what do I do about it."
- **Principal / Registrar / Management (privileged)** — sees the **whole institution**. Their home is a **Dashboard** (designed after the two screens here; it reuses this system).
- A student is either a **minor** (under 18 — many first-years are) or an adult. This is not cosmetic: contacting a minor's parent requires recorded consent (§5, the badge; and it shapes the intervention UI).

---

## 3. The real backend data (design only with these fields)

These are the actual API responses the screens bind to. Design to exactly these shapes.

### 3a. At-risk list — `GET /risk/students` (the Risk Board's data)
A ranked list, highest score first. Each item:
```
student_id        : uuid
roll_no           : "21CSE045"
name              : "Aarav Sharma"
tier              : "high" | "watch" | "low"
overall_score     : 0–100  (e.g. 78.0)
subject_minor_status : "minor" | "adult" | "unknown"
department        : "CSE"
top_findings      : [ up to ~3 finding summaries, see 3c ]
computed_at       : "2026-06-22T18:30:00Z"
```
Filterable by tier, risk_type. **By default the board shows watch + high only** (low isn't "at risk").

### 3b. Student 360 — `GET /students/{id}` + `GET /risk/students/{id}`
Profile + the full risk picture:
```
profile   : { roll_no, name, department, programme, admission_year, dob (=> minor/adult) }
current   : { tier, overall_score, subject_minor_status, computed_at }
findings  : [ finding objects, see 3c — the full set, not just top 3 ]
history   : [ { tier, overall_score, computed_at } ... ]   # past assessments, for a tier-over-time timeline
interventions : [ { type, status, title, assigned_to_name, created_at,
                    outcome? } ... ]
```

### 3c. A finding (the "why" — the most important content on the page)
Each finding is a reason with the evidence behind it. **The five finding types that exist** (there are no others):
```
code      : machine code (below)
risk_type : "attendance" | "academic" | "fee"
severity  : "high" | "medium" | "low"
message   : human-readable, e.g. "Attendance 61% in DBMS (below 75%)"
evidence  : the numbers, e.g. { course: "DBMS", value: 61, threshold: 75 }
```
| code | type | example message |
|---|---|---|
| `ATTENDANCE_BELOW_THRESHOLD` | attendance | "Attendance 61% (below 75%)" |
| `ATTENDANCE_DECLINING` | attendance | "Attendance fell 18 pts (82%→64%)" |
| `ACADEMIC_FAILING_INTERNALS` | academic | "2 internals below 40%" |
| `ACADEMIC_DECLINE` | academic | "Latest internal 38% vs baseline 64%" |
| `FEE_OVERDUE` | fee | "Fees overdue 41 days" |

### 3d. Tiers & how the score works (so the visuals are honest)
- **high** (score ≥ 50), **watch** (25–49), **low** (< 25). Score = sum of finding weights, capped at 100.
- A `low` student with *only* an overdue-fee finding can exist and is **excluded from the at-risk board by default** — fees alone isn't academic risk.
- Tier always shows as **label + colour**, never colour alone (some users are colour-blind; the engine is advisory, the human decides — clarity matters).

### 3e. Interventions (the action loop)
Types: `mentor_meeting`, `remedial_class`, `parent_contact`, `counselling`, `other`.
Statuses: `suggested → open → in_progress → completed` (or `dismissed`).
Outcome (recorded later): `improved | no_change | worsened | unknown`.
**parent_contact for a minor/unknown student requires an explicit recorded-consent confirmation** before it can be created — design this as a deliberate, gated step, never a one-click default.

### 3f. Freshness
Risk data is recomputed when new data is imported. An import can finish with recompute `ok | partial | failed`. When it's not `ok`, the UI shows a quiet "risk scores may be out of date" note — design a calm, non-blocking treatment for this.

---

## 4. Realistic seed content (use this exact content — it's what makes the design real)

**Faculty:** Dr. Meera Iyer, mentor for CSE 3rd year, Sections A & B.

**Her at-risk cohort (board rows, already ranked):**

| roll_no | name | tier | score | minor | dept | top findings | computed_at |
|---|---|---|---|---|---|---|---|
| 21CSE045 | Aarav Sharma | high | 78 | adult | CSE | "Attendance 61% (below 75%)" · "2 internals below 40%" | 2 hrs ago |
| 21CSE112 | Sneha Reddy | high | 60 | adult | CSE | "Attendance fell 18 pts (82%→64%)" · "Latest internal 38% vs baseline 64%" | 2 hrs ago |
| 21CSE009 | Mohammed Faiz | high | 55 | adult | CSE | "2 internals below 40%" · "Fees overdue 41 days" | 2 hrs ago |
| 21CSE077 | Ananya Nair | watch | 40 | minor | CSE | "Attendance 71% (below 75%)" | 2 hrs ago |
| 21CSE131 | Rohit Verma | watch | 35 | adult | CSE | "Latest internal 44% vs baseline 61%" | 2 hrs ago |
| 21CSE058 | Diya Patel | watch | 25 | minor | CSE | "Attendance fell 16 pts (80%→64%)" | 2 hrs ago |

(Note one **minor** in watch — Ananya Nair — so the minor badge appears on the board; and Mohammed Faiz mixes academic + fee findings.)

**Student 360 — design it for Aarav Sharma (21CSE045):**
- Profile: CSE, B.Tech Computer Science, admission 2021, adult.
- Current: high, score 78, computed 2 hrs ago.
- Findings (full set): `ATTENDANCE_BELOW_THRESHOLD` "Attendance 61% (below 75%)" {value 61, threshold 75}; `ACADEMIC_FAILING_INTERNALS` "2 internals below 40%" {count 2, threshold 40}; `ACADEMIC_DECLINE` "Latest internal 38% vs baseline 64%" {latest 38, baseline 64}.
- History (tier timeline): low (8 weeks ago, score 10) → watch (5 weeks ago, 30) → watch (3 weeks ago, 45) → high (now, 78). A clear, worsening trajectory — the timeline should make that legible at a glance.
- Interventions: one existing — `mentor_meeting`, status `completed`, "1:1 check-in on attendance", by Dr. Meera Iyer, 1 week ago, outcome `no_change`. Plus the affordance to add a new one.

**Dashboard summary (for the system that inherits from these two screens, design later):**
- Total assessed 1,240 · high 86 · watch 211 · low 943.
- By department: CSE 320 (28 high), MECH 280 (12 high), ECE 240 (19 high), CIVIL 210 (9 high), Unassigned 190 (18 high).

---

## 5. Visual direction (direction, not dictation — make deliberate choices)

**The feeling:** a calm, credible **institutional decision console** — something a principal trusts and a mentor opens every day under time pressure. Closer to a well-made clinical / operations console than a consumer app or a marketing page. **Density with clarity** beats flourish; this screen is read, not admired.

**Steer away from the AI-default looks** — do not produce cream-background + high-contrast serif + terracotta; near-black + single acid-green/vermilion accent; or broadsheet hairline-rule columns. None of those fit a serious institutional tool, and they signal "templated."

**Token system to define (then design from it):**
- **Palette (4–6 named roles):** a quiet neutral surface (not pure white, not cream), a deep professional ink for text, **one** confident accent for primary actions/links, plus the tier ramp below. WCAG-AA contrast throughout.
- **Tier ramp (the signature):** a **colour-vision-safe** encoding of `high / watch / low`, always shown as **colour + text label** (and optionally a small shape). This consistent tier language, reused on the board, the 360 score, the history timeline, and the dashboard tiles, **is the product's visual identity** — spend your boldness here and keep everything else quiet.
- **Type (2–3 roles):** a restrained, characterful face for headings and the big risk numbers; a highly legible UI/body face (tables must stay readable at density); and **tabular figures for all numbers** so scores and percentages align in columns.

**The signature element:** the tier visual language + the "show the why" treatment — how a finding's reason and its evidence number read at a glance in a dense row. Get those two right and the whole system feels intentional.

**Copy is design material:** active voice; name things by what the user controls ("at-risk students", "log intervention"), never by how the system is built ("assessment rows"); an action keeps its name through the flow ("Log intervention" → "Intervention logged").

---

## 6. The two screens to design (design these; everything else inherits)

1. **Faculty Risk Board** (`/board`) — Dr. Meera Iyer's cohort from §4. A scannable ranked list: name + roll, tier (label+colour), score, the top 1–3 finding reasons inline, last-computed time, the minor badge where relevant, filters (tier / risk type), and a per-row "Log intervention" affordance. **The test of this screen: a mentor glances and instantly knows who needs help and why.**
2. **Student 360** (`/students/:id`) — Aarav Sharma from §4. Identity + current tier/score, the **full findings list with evidence**, a **tier-over-time history timeline** (his low→watch→watch→high trajectory should be obvious), and the interventions (the completed one + the affordance to add a new one, including how the **minor consent gate** would look when adding `parent_contact`).

---

## 7. States to design (not just the happy path)

- **Empty board:** Dr. Iyer's cohort has nobody flagged. Directional, not a void — e.g. "No students in your cohort are flagged right now." Make emptiness feel like good news, not a broken page.
- **Error:** the risk data failed to load. Says what happened and the way forward, in the interface's voice — never "Oops!" or an apology.
- **Stale-data note (§3f):** the calm, non-blocking "risk scores may be out of date" treatment.
- **The minor consent gate:** the moment of adding `parent_contact` for a minor — show the explicit consent confirmation, designed as a deliberate step, not a nag.

---

## 8. Quality floor (bake in, don't announce)
Responsive to mobile (a mentor will open the board on a phone). Visible keyboard focus. Reduced motion respected. Tier legible without colour. Numbers in tabular figures. Nothing that reads as decoration-for-its-own-sake.

---

## 9. Out of scope for this design pass
Login, config editor, imports list, alerts, the NL-query box, accreditation views, student self-service — none of these now. Design the two screens in §6 well; the rest of the system inherits their language. (Leave a sensible spot in the nav for a future search/NL box, but don't design it.)
```

**Deliver:** the two screens (§6) with their states (§7), built from the real seed content (§4) and data shapes (§3), in a visual identity you've made deliberate choices about per §5.
