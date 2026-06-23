"""Resolves a user's visible student_ids by role + FacultyScope (spec §5.9 of
Phase 1 extended by Phase 2 §4.7/§13), and the reverse direction (which
faculty have a given student in scope) used by alert recipient resolution
(spec §11).
"""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.canonical import Course, Department, Enrollment, Programme, Student
from app.models.risk import FacultyScope

PRIVILEGED_ROLES = ("admin", "principal", "registrar", "iqac")
"""Spec §13 names the full-visibility group as "admin/principal/registrar/
management" but VALID_ROLES (app/models/user.py, Phase 0, locked) has no
"management" role. The closest faithful read is "every role besides faculty
and student" -- i.e. everything else Phase 0/1 already defined (decision
recorded in CHANGELOG.md)."""


def has_full_visibility(role: str) -> bool:
    return role in PRIVILEGED_ROLES


def visible_student_ids(session: Session, tenant_id: UUID, role: str, user_id: UUID) -> set[UUID] | None:
    """None means "all tenant students" (privileged roles). Faculty get the
    explicit set resolved from their FacultyScope rows; any other role
    (student, or anything unrecognized) gets an empty set -- spec §13 routes
    the student role to 403 at the route layer, not a 200 with zero rows."""
    if has_full_visibility(role):
        return None
    if role != "faculty":
        return set()

    scopes = session.execute(
        select(FacultyScope.scope_type, FacultyScope.scope_ref).where(
            FacultyScope.tenant_id == tenant_id, FacultyScope.user_id == user_id
        )
    ).all()
    if not scopes:
        return set()

    student_ids: set[UUID] = set()
    for scope_type, scope_ref in scopes:
        student_ids |= _students_for_scope(session, tenant_id, scope_type, scope_ref)
    return student_ids


def _students_for_scope(session: Session, tenant_id: UUID, scope_type: str, scope_ref: str) -> set[UUID]:
    if scope_type == "department":
        rows = session.execute(
            select(Student.id)
            .join(Programme, Programme.id == Student.programme_id)
            .join(Department, Department.id == Programme.department_id)
            .where(Student.tenant_id == tenant_id, Department.code == scope_ref)
        ).scalars().all()
    elif scope_type == "programme":
        rows = session.execute(
            select(Student.id)
            .join(Programme, Programme.id == Student.programme_id)
            .where(Student.tenant_id == tenant_id, Programme.code == scope_ref)
        ).scalars().all()
    elif scope_type in ("course", "section"):
        # The Phase 1 schema (locked) has no distinct "section" column on
        # enrollment/courses -- treated as a synonym for course code, the
        # closest existing granularity (decision recorded in CHANGELOG.md).
        rows = session.execute(
            select(Enrollment.student_id)
            .join(Course, Course.id == Enrollment.course_id)
            .where(Enrollment.tenant_id == tenant_id, Course.code == scope_ref)
        ).scalars().all()
    else:
        rows = []
    return set(rows)


def faculty_user_ids_for_student(session: Session, tenant_id: UUID, student_id: UUID) -> list[UUID]:
    """Reverse direction for alert recipient resolution (spec §11): which
    faculty users have this student in their scope, via department/
    programme/course-or-section."""
    student = session.get(Student, student_id)
    if student is None:
        return []

    candidate_refs: list[tuple[str, str]] = []
    programme = session.get(Programme, student.programme_id) if student.programme_id else None
    if programme is not None:
        candidate_refs.append(("programme", programme.code))
        if programme.department_id:
            department = session.get(Department, programme.department_id)
            if department is not None:
                candidate_refs.append(("department", department.code))

    course_codes = session.execute(
        select(Course.code)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(Enrollment.tenant_id == tenant_id, Enrollment.student_id == student_id)
    ).scalars().all()
    for code in course_codes:
        candidate_refs.append(("course", code))
        candidate_refs.append(("section", code))

    if not candidate_refs:
        return []

    conditions = [
        (FacultyScope.scope_type == scope_type) & (FacultyScope.scope_ref == scope_ref)
        for scope_type, scope_ref in candidate_refs
    ]
    rows = session.execute(
        select(FacultyScope.user_id).where(FacultyScope.tenant_id == tenant_id, or_(*conditions))
    ).scalars().all()
    return list(dict.fromkeys(rows))
