"""Idempotent demo-tenant seeder (Phase 3 spec §C.1).

Writes canonical rows directly (bypassing ingestion + entity resolution, on
purpose -- spec note above §C.2) so the named CSE cohort produces exact,
predictable findings/tiers, then calls recompute_for_tenant once to generate
real risk_assessments/findings/alerts from the engine. Run from `backend/`:

    python -m scripts.seed_demo
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.rls import set_tenant_context
from app.core.security import hash_password
from app.models.canonical import Attendance, Course, Department, Fee, InternalMark, Programme, Student
from app.models.ingestion import SourceSystem
from app.models.risk import FacultyScope, Intervention, InterventionOutcome, RiskAssessment
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.risk_repository import RiskRepository
from app.services.risk.engine import recompute_for_tenant

TENANT_NAME = "Demo Engineering College"
TENANT_SLUG = "demo-eng"
DEMO_PASSWORD = "Demo@12345"
TODAY = date.today()


def even_spread(n: int, present_count: int) -> list[bool]:
    """Evenly distributes `present_count` True flags across n slots (Floyd's
    "evenly distribute k of n" algorithm), so any contiguous sub-window's
    local percentage stays close to the global one. Used so seed students
    meant to trigger only the *overall* attendance-threshold rule don't also
    spuriously trip the trend-decline rule (the engine's confirmed-by-running
    behaviour -- see CHANGELOG.md for the verification)."""
    result = []
    acc = 0
    for _ in range(n):
        acc += present_count
        if acc >= n:
            acc -= n
            result.append(True)
        else:
            result.append(False)
    return result


def _stamp(entity, source_system_id: UUID, record_id: str) -> None:
    entity.source_system_id = source_system_id
    entity.source_record_id = record_id
    entity.ingested_at = datetime.now(UTC)


def _get_or_create_tenant(session: Session) -> tuple[Tenant, bool]:
    existing = session.execute(select(Tenant).where(Tenant.slug == TENANT_SLUG)).scalar_one_or_none()
    if existing is not None:
        return existing, False
    tenant = Tenant(name=TENANT_NAME, slug=TENANT_SLUG)
    session.add(tenant)
    session.flush()
    return tenant, True


def _create_source_system(session: Session, tenant_id: UUID) -> SourceSystem:
    source = SourceSystem(tenant_id=tenant_id, name="seed", precedence=999)
    session.add(source)
    session.flush()
    return source


def _create_users(session: Session, tenant_id: UUID) -> dict[str, User]:
    users: dict[str, User] = {}
    for email, role in (
        ("principal@demo-eng.edu", "principal"),
        ("meera.iyer@demo-eng.edu", "faculty"),
        ("admin@demo-eng.edu", "admin"),
    ):
        user = User(tenant_id=tenant_id, email=email, password_hash=hash_password(DEMO_PASSWORD), role=role)
        session.add(user)
        session.flush()
        users[email] = user
    return users


def _create_departments_and_programmes(
    session: Session, tenant_id: UUID, source_system_id: UUID
) -> dict[str, tuple[Department, Programme]]:
    by_dept: dict[str, tuple[Department, Programme]] = {}
    for dept_code, prog_name, prog_code in (
        ("CSE", "B.Tech Computer Science", "BTECH-CSE"),
        ("MECH", "B.Tech Mechanical Engineering", "BTECH-MECH"),
        ("ECE", "B.Tech Electronics & Communication", "BTECH-ECE"),
        ("CIVIL", "B.Tech Civil Engineering", "BTECH-CIVIL"),
    ):
        department = Department(tenant_id=tenant_id, code=dept_code, name=dept_code)
        _stamp(department, source_system_id, f"dept-{dept_code}")
        session.add(department)
        session.flush()

        programme = Programme(tenant_id=tenant_id, code=prog_code, name=prog_name, department_id=department.id)
        _stamp(programme, source_system_id, f"prog-{prog_code}")
        session.add(programme)
        session.flush()

        by_dept[dept_code] = (department, programme)
    return by_dept


def _create_courses(
    session: Session, tenant_id: UUID, programme_id: UUID, codes: list[str], source_system_id: UUID
) -> dict[str, Course]:
    courses: dict[str, Course] = {}
    for code in codes:
        course = Course(tenant_id=tenant_id, code=code, name=code, programme_id=programme_id)
        _stamp(course, source_system_id, f"course-{code}")
        session.add(course)
        session.flush()
        courses[code] = course
    return courses


def _create_student(
    session: Session,
    tenant_id: UUID,
    roll_no: str,
    name: str,
    dob: date | None,
    programme_id: UUID | None,
    source_system_id: UUID,
) -> Student:
    student = Student(
        tenant_id=tenant_id,
        canonical_roll_no=roll_no,
        name=name,
        dob=dob,
        admission_year=2021,
        programme_id=programme_id,
        status="active",
    )
    _stamp(student, source_system_id, roll_no)
    session.add(student)
    session.flush()
    return student


def _add_attendance(
    session: Session,
    tenant_id: UUID,
    student: Student,
    course_ids: list[UUID],
    presents: list[bool],
    source_system_id: UUID,
) -> None:
    start_date = TODAY - timedelta(days=len(presents))
    for i, present in enumerate(presents):
        row = Attendance(
            tenant_id=tenant_id,
            student_id=student.id,
            course_id=course_ids[i % len(course_ids)],
            class_date=start_date + timedelta(days=i),
            session_no=1,
            status="present" if present else "absent",
        )
        _stamp(row, source_system_id, f"{student.canonical_roll_no}-att-{i}")
        session.add(row)


def _add_marks(
    session: Session,
    tenant_id: UUID,
    student: Student,
    course_id: UUID,
    marks: list[int],
    source_system_id: UUID,
) -> None:
    gap_days = 30
    start_date = TODAY - timedelta(days=gap_days * len(marks))
    for i, obtained in enumerate(marks):
        row = InternalMark(
            tenant_id=tenant_id,
            student_id=student.id,
            course_id=course_id,
            assessment_type=f"CT{i + 1}",
            attempt=1,
            max_marks=Decimal(100),
            obtained=Decimal(obtained),
            assessment_date=start_date + timedelta(days=gap_days * i),
        )
        _stamp(row, source_system_id, f"{student.canonical_roll_no}-mark-{i}")
        session.add(row)


def _add_fee(
    session: Session, tenant_id: UUID, student: Student, overdue_days: int | None, source_system_id: UUID
) -> None:
    due_date = TODAY - timedelta(days=overdue_days) if overdue_days else TODAY + timedelta(days=60)
    row = Fee(
        tenant_id=tenant_id,
        student_id=student.id,
        term="2025-S2",
        fee_head="Tuition",
        amount_due=Decimal(60000),
        amount_paid=Decimal(0),
        due_date=due_date,
    )
    _stamp(row, source_system_id, f"{student.canonical_roll_no}-fee")
    session.add(row)


# Named CSE cohort (Phase 3 spec §C.2). Attendance/marks/fee values verified
# against the live RulesRiskEvaluator (see CHANGELOG.md) to produce exactly
# the findings/tiers the spec table names -- two values differ in the last
# digit from the spec's illustrative percentages (Ananya/Diya 70% not 71%,
# Karthik 96% not 95%) purely because the spec's session counts don't divide
# evenly; the rule outcomes are identical either way.
_NAMED_COHORT = [
    {
        "roll": "21CSE045",
        "name": "Aarav Sharma",
        "dob": date(2003, 4, 12),
        "attendance": even_spread(100, 60),
        "marks": [70, 36, 32],
        "fee_overdue_days": None,
    },
    {
        "roll": "21CSE009",
        "name": "Mohammed Faiz",
        "dob": date(2003, 1, 20),
        "attendance": even_spread(50, 39),
        "marks": [33, 35],
        "fee_overdue_days": 41,
    },
    {
        "roll": "21CSE112",
        "name": "Sneha Reddy",
        "dob": date(2003, 8, 30),
        "attendance": even_spread(76, 59) + [True] * 10 + [False] * 2 + [True] * 8 + [False] * 4,
        "marks": [66, 47],
        "fee_overdue_days": None,
    },
    {
        "roll": "21CSE077",
        "name": "Ananya Nair",
        "dob": date(2008, 10, 12),  # minor
        "attendance": even_spread(30, 21),
        "marks": [58, 55],
        "fee_overdue_days": None,
    },
    {
        "roll": "21CSE058",
        "name": "Diya Patel",
        "dob": date(2008, 12, 1),  # minor
        "attendance": even_spread(30, 21),
        "marks": [72, 70],
        "fee_overdue_days": None,
    },
    {
        "roll": "21CSE131",
        "name": "Rohit Verma",
        "dob": date(2003, 6, 5),
        "attendance": even_spread(50, 40),
        "marks": [61, 44],
        "fee_overdue_days": None,
    },
    {
        "roll": "21CSE200",
        "name": "Karthik Menon",
        "dob": date(2003, 3, 3),
        "attendance": even_spread(50, 48),
        "marks": [75, 78],
        "fee_overdue_days": 35,
    },
]

_FILLER_ROLL_NUMBERS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18]
_FILLER_NAMES = [
    "Priya Iyer",
    "Rahul Krishnan",
    "Sanya Gupta",
    "Vikram Rao",
    "Arjun Kumar",
    "Divya Menon",
    "Karan Singh",
    "Pooja Reddy",
    "Aditya Verma",
    "Nikhil Joshi",
    "Tanvi Shah",
    "Rohan Desai",
    "Ishita Bose",
    "Siddharth Nair",
    "Kavya Krishnan",
    "Varun Pillai",
    "Neha Agarwal",
]

_OTHER_DEPT_NAMES = [
    "Akash Mehta",
    "Bhavna Rathi",
    "Chetan Yadav",
    "Deepika Suresh",
    "Eshwar Pillai",
    "Farah Sheikh",
    "Gaurav Malhotra",
    "Harini Subramaniam",
    "Imran Khan",
    "Jyoti Bhatt",
    "Kunal Saxena",
    "Lavanya Iyer",
    "Manoj Tiwari",
    "Nandini Rao",
    "Om Prakash",
    "Pallavi Joshi",
    "Quasim Ali",
    "Rashmi Nambiar",
    "Sahil Kapoor",
    "Trisha Banerjee",
    "Uday Chauhan",
    "Vidya Krishnamurthy",
    "Wasim Ansari",
    "Yamini Pawar",
    "Zoya Ahmed",
    "Abhinav Bhatt",
    "Charu Lakhani",
    "Devansh Oberoi",
    "Esha Trivedi",
    "Faizan Sheikh",
    "Gita Nair",
    "Harsh Vardhan",
    "Inaya Sayed",
    "Jatin Mahajan",
    "Kiran Bedi",
    "Lokesh Reddy",
    "Maya Sundaram",
    "Naveen Choudhary",
    "Ojas Deshpande",
    "Priyanka Bose",
    "Qadir Baig",
    "Riya Sharma",
    "Sameer Kulkarni",
    "Tara Menon",
    "Umang Shah",
    "Vivaan Kapoor",
    "Wendy Fernandes",
    "Yash Thakur",
    "Zara Hussain",
    "Ananth Iyer",
    "Bela Shah",
    "Chirag Patel",
    "Disha Goel",
    "Elina Roy",
    "Farhan Qureshi",
]


def _other_dept_profile(index: int) -> tuple[list[bool], list[int]]:
    """~70% clean / ~20% watch / ~10% high spread, deterministic by index so
    re-running the script (after a skip-if-exists no-op) is reproducible."""
    bucket = index % 10
    if bucket == 9:
        return even_spread(40, 22), [50, 30]  # -> high
    if bucket in (7, 8):
        return even_spread(40, 27), [60, 62]  # -> watch
    return even_spread(60, 54), [65, 68]  # -> low / clean


def _seed_named_cohort(
    session: Session,
    tenant_id: UUID,
    cse_programme_id: UUID,
    cse_course_ids: list[UUID],
    primary_course_id: UUID,
    source_system_id: UUID,
    faculty: User,
) -> dict[str, Student]:
    students: dict[str, Student] = {}
    for spec in _NAMED_COHORT:
        student = _create_student(
            session, tenant_id, spec["roll"], spec["name"], spec["dob"], cse_programme_id, source_system_id
        )
        _add_attendance(session, tenant_id, student, cse_course_ids, spec["attendance"], source_system_id)
        _add_marks(session, tenant_id, student, primary_course_id, spec["marks"], source_system_id)
        _add_fee(session, tenant_id, student, spec["fee_overdue_days"], source_system_id)
        students[spec["roll"]] = student

    # Worsening history demo for Aarav (spec §C.6): two superseded
    # assessments before today's engine-computed current one, so the 360's
    # history timeline shows low -> watch -> high.
    aarav = students["21CSE045"]
    for tier, score, days_ago in (("low", 10.0, 60), ("watch", 35.0, 21)):
        session.add(
            RiskAssessment(
                tenant_id=tenant_id,
                student_id=aarav.id,
                is_current=False,
                model_type="rules",
                model_version="1.0",
                config_version=1,
                overall_score=score,
                tier=tier,
                subject_minor_status="adult",
                signals_snapshot={},
                triggered_by="manual",
                computed_at=datetime.now(UTC) - timedelta(days=days_ago),
            )
        )

    # Completed mentor-meeting intervention for Aarav (spec §C.6).
    intervention = Intervention(
        tenant_id=tenant_id,
        student_id=aarav.id,
        type="mentor_meeting",
        status="completed",
        title="Mentor check-in with Dr. Iyer",
        notes="Discussed declining DBMS internals and attendance; agreed a remedial study plan.",
        assigned_to=faculty.id,
        created_by=faculty.id,
    )
    session.add(intervention)
    session.flush()
    session.add(
        InterventionOutcome(
            tenant_id=tenant_id,
            intervention_id=intervention.id,
            outcome="no_change",
            notes="Follow-up scheduled after the next internal assessment cycle.",
            recorded_by=faculty.id,
        )
    )
    return students


def _seed_filler_cohort(
    session: Session,
    tenant_id: UUID,
    cse_programme_id: UUID,
    cse_course_ids: list[UUID],
    primary_course_id: UUID,
    source_system_id: UUID,
) -> None:
    for roll_num, name in zip(_FILLER_ROLL_NUMBERS, _FILLER_NAMES, strict=True):
        student = _create_student(
            session, tenant_id, f"21CSE{roll_num:03d}", name, date(2003, 5, 15), cse_programme_id, source_system_id
        )
        _add_attendance(session, tenant_id, student, cse_course_ids, even_spread(60, 54), source_system_id)
        _add_marks(session, tenant_id, student, primary_course_id, [65, 68], source_system_id)
        _add_fee(session, tenant_id, student, None, source_system_id)


def _seed_other_departments(
    session: Session,
    tenant_id: UUID,
    dept_programmes: dict[str, tuple[Department, Programme]],
    dept_courses: dict[str, Course],
    source_system_id: UUID,
) -> None:
    other_depts = ["MECH", "ECE", "CIVIL"]
    total_with_dept = 40
    total_unassigned = 15

    for i, name in enumerate(_OTHER_DEPT_NAMES[: total_with_dept + total_unassigned]):
        if i < total_with_dept:
            dept_code = other_depts[i % len(other_depts)]
            programme_id = dept_programmes[dept_code][1].id
            course_id = dept_courses[dept_code].id
            roll_no = f"21{dept_code}{i:03d}"
        else:
            programme_id = None
            course_id = dept_courses["MECH"].id  # any course works -- attendance is keyed by student, not department
            roll_no = f"21UNA{i:03d}"

        student = _create_student(session, tenant_id, roll_no, name, date(2003, 9, 1), programme_id, source_system_id)
        presents, marks = _other_dept_profile(i)
        _add_attendance(session, tenant_id, student, [course_id], presents, source_system_id)
        _add_marks(session, tenant_id, student, course_id, marks, source_system_id)
        _add_fee(session, tenant_id, student, None, source_system_id)


def seed() -> None:
    session = SessionLocal()
    try:
        with session.begin():
            tenant, created = _get_or_create_tenant(session)
            set_tenant_context(session, tenant.id)

            if created:
                source = _create_source_system(session, tenant.id)
                users = _create_users(session, tenant.id)
                dept_programmes = _create_departments_and_programmes(session, tenant.id, source.id)
                cse_department, cse_programme = dept_programmes["CSE"]
                cse_courses = _create_courses(
                    session, tenant.id, cse_programme.id, ["DBMS", "OS", "CN", "TOC"], source.id
                )
                cse_course_ids = [c.id for c in cse_courses.values()]
                primary_course_id = cse_courses["DBMS"].id

                dept_courses = {"CSE": cse_courses["DBMS"]}
                for dept_code in ("MECH", "ECE", "CIVIL"):
                    _, programme = dept_programmes[dept_code]
                    courses = _create_courses(session, tenant.id, programme.id, [f"{dept_code}101"], source.id)
                    dept_courses[dept_code] = courses[f"{dept_code}101"]

                faculty = users["meera.iyer@demo-eng.edu"]
                session.add(
                    FacultyScope(
                        tenant_id=tenant.id, user_id=faculty.id, scope_type="department", scope_ref="CSE",
                        created_by=users["admin@demo-eng.edu"].id,
                    )
                )

                _seed_named_cohort(
                    session, tenant.id, cse_programme.id, cse_course_ids, primary_course_id, source.id, faculty
                )
                _seed_filler_cohort(
                    session, tenant.id, cse_programme.id, cse_course_ids, primary_course_id, source.id
                )
                _seed_other_departments(session, tenant.id, dept_programmes, dept_courses, source.id)
                session.flush()
                print(f"Created tenant '{TENANT_NAME}' (slug={TENANT_SLUG}, id={tenant.id}).")
            else:
                print(f"Tenant '{TENANT_NAME}' (slug={TENANT_SLUG}) already exists -- skipping data creation.")

            summary = recompute_for_tenant(session, tenant.id, triggered_by="manual")

        print()
        print("Login credentials (password for all): " + DEMO_PASSWORD)
        print("  principal@demo-eng.edu  (role: principal -- Dashboard)")
        print("  meera.iyer@demo-eng.edu (role: faculty, scope: department=CSE -- Risk Board)")
        print("  admin@demo-eng.edu      (role: admin)")
        print()
        print(f"Tenant id: {tenant.id}")
        print(
            f"Recompute summary: evaluated={summary.evaluated} changed={summary.changed} "
            f"unchanged={summary.unchanged} skipped={summary.skipped} errors={len(summary.errors)}"
        )

        with session.begin():
            set_tenant_context(session, tenant.id)
            data = RiskRepository(session, tenant.id).summary(student_ids=None)
            print(f"Tier counts: {data['by_tier']} (total_assessed={data['total_assessed']})")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
