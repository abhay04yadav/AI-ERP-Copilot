"""Bulk attendance signal computation (spec §5.2). One aggregate query set for
the whole batch of target students — never a per-student round trip, so this
scales independently of student count (spec §1, §14, acceptance test §15.13).
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.canonical import Attendance, Course
from app.services.risk.signals.base import CourseAttendance

_PRESENT = "present"


def compute_attendance_signals(
    session: Session, tenant_id: UUID, student_ids: list[UUID], config: dict
) -> dict[UUID, dict]:
    """Returns, per student_id, the attendance fields of StudentSignals:
    overall_attendance_pct, overall_sessions, attendance_by_course,
    attendance_recent_pct, attendance_prior_pct."""
    if not student_ids:
        return {}

    trend_window = config["attendance_trend_window"]

    per_course_rows = session.execute(
        select(
            Attendance.student_id,
            Course.code,
            Course.name,
            func.count().label("total"),
            func.sum(case((Attendance.status == _PRESENT, 1), else_=0)).label("present"),
        )
        .join(Course, Course.id == Attendance.course_id)
        .where(
            Attendance.tenant_id == tenant_id,
            Attendance.student_id.in_(student_ids),
            Attendance.is_deleted.is_(False),
        )
        .group_by(Attendance.student_id, Course.id, Course.code, Course.name)
    ).all()

    by_student_courses: dict[UUID, list] = defaultdict(list)
    for row in per_course_rows:
        by_student_courses[row.student_id].append(row)

    # Ordered raw rows for the trend windows — chronological pct can't be
    # expressed as a single GROUP BY aggregate, so this is computed from
    # bulk-fetched, deterministically ordered rows instead (still one query
    # for the whole batch, not per student).
    ordered_rows = session.execute(
        select(Attendance.student_id, Attendance.status)
        .where(
            Attendance.tenant_id == tenant_id,
            Attendance.student_id.in_(student_ids),
            Attendance.is_deleted.is_(False),
        )
        .order_by(Attendance.student_id, Attendance.class_date, Attendance.session_no, Attendance.course_id)
    ).all()

    by_student_ordered: dict[UUID, list] = defaultdict(list)
    for row in ordered_rows:
        by_student_ordered[row.student_id].append(row.status)

    result: dict[UUID, dict] = {}
    for student_id in student_ids:
        course_rows = by_student_courses.get(student_id, [])
        attendance_by_course = tuple(
            CourseAttendance(
                course_code=row.code,
                course_name=row.name,
                present=int(row.present),
                total=int(row.total),
                pct=round(100 * row.present / row.total, 2) if row.total else None,
            )
            for row in course_rows
        )
        overall_present = sum(int(row.present) for row in course_rows)
        overall_total = sum(int(row.total) for row in course_rows)
        overall_pct = round(100 * overall_present / overall_total, 2) if overall_total else None

        recent_pct, prior_pct = _trend_windows(by_student_ordered.get(student_id, []), trend_window)

        result[student_id] = {
            "overall_attendance_pct": overall_pct,
            "overall_sessions": overall_total,
            "attendance_by_course": attendance_by_course,
            "attendance_recent_pct": recent_pct,
            "attendance_prior_pct": prior_pct,
        }
    return result


def _trend_windows(statuses: list[str], window: int) -> tuple[float | None, float | None]:
    """Both windows require a full `window` of sessions each (2*window total
    sessions) to be populated — a partial window is not "the window" the
    config asked for, so trend findings stay silent rather than fire on a
    sampling artifact (same confidence-guard spirit as the attendance-below-
    threshold rule's min-sessions check, spec §6.3 note)."""
    if len(statuses) < 2 * window:
        return None, None

    def pct(chunk: list[str]) -> float:
        return round(100 * sum(1 for s in chunk if s == _PRESENT) / len(chunk), 2)

    recent = statuses[-window:]
    prior = statuses[-2 * window : -window]
    return pct(recent), pct(prior)
