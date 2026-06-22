from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_tenant_session
from app.core.exceptions import NotFoundException
from app.models.canonical import Attendance, Fee, InternalMark, Student
from app.schemas.students import AttendanceSummary, FeeSummary, InternalMarkSummary, Student360Response

router = APIRouter(prefix="/students", tags=["students"])


@router.get("/{student_id}", response_model=Student360Response)
def get_student_360(
    student_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> Student360Response:
    """Unified record assembled across canonical tables (spec §5.9) — the
    proof-of-life read that the future Student Success Engine extends."""
    student = session.execute(
        select(Student).where(Student.tenant_id == current_user.tenant_id, Student.id == student_id)
    ).scalar_one_or_none()
    if student is None:
        raise NotFoundException("Student not found.")

    attendance_rows = session.execute(
        select(Attendance).where(Attendance.tenant_id == current_user.tenant_id, Attendance.student_id == student_id)
    ).scalars().all()
    by_course: dict[UUID, list[Attendance]] = {}
    for row in attendance_rows:
        by_course.setdefault(row.course_id, []).append(row)
    attendance_summary = [
        AttendanceSummary(
            course_id=course_id,
            total_sessions=len(rows),
            present_sessions=sum(1 for r in rows if r.status == "present"),
            percentage=round(100 * sum(1 for r in rows if r.status == "present") / len(rows), 2) if rows else 0.0,
        )
        for course_id, rows in by_course.items()
    ]

    marks_rows = session.execute(
        select(InternalMark).where(
            InternalMark.tenant_id == current_user.tenant_id, InternalMark.student_id == student_id
        )
    ).scalars().all()
    marks = [
        InternalMarkSummary(
            course_id=row.course_id,
            assessment_type=row.assessment_type,
            attempt=row.attempt,
            max_marks=row.max_marks,
            obtained=row.obtained,
        )
        for row in marks_rows
    ]

    fee_rows = session.execute(
        select(Fee).where(Fee.tenant_id == current_user.tenant_id, Fee.student_id == student_id)
    ).scalars().all()
    fees = [
        FeeSummary(
            term=row.term, fee_head=row.fee_head, amount_due=row.amount_due, amount_paid=row.amount_paid, status=row.status
        )
        for row in fee_rows
    ]

    return Student360Response(
        id=student.id,
        canonical_roll_no=student.canonical_roll_no,
        name=student.name,
        dob=student.dob,
        gender=student.gender,
        category=student.category,
        email=student.email,
        phone=student.phone,
        admission_year=student.admission_year,
        programme_id=student.programme_id,
        status=student.status,
        attendance_summary=attendance_summary,
        marks=marks,
        fees=fees,
    )
