"""Bulk academic signal computation (spec §5.2). One ordered bulk query for
the whole batch of target students.

internal_marks (Phase 1, locked schema) has no term/sequence column to order
by, so created_at is used as the stable proxy for "most recent" — the only
deterministic ordering key the canonical schema actually provides (decision
recorded in CHANGELOG.md).
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import Course, InternalMark


def compute_academic_signals(
    session: Session, tenant_id: UUID, student_ids: list[UUID], config: dict
) -> dict[UUID, dict]:
    """Returns, per student_id, the academic fields of StudentSignals:
    latest_internal_pct_by_course, failing_internal_count,
    academic_latest_pct, academic_baseline_pct."""
    if not student_ids:
        return {}

    fail_pct = config["academic_fail_pct"]

    rows = session.execute(
        select(
            InternalMark.student_id,
            InternalMark.id,
            Course.code,
            InternalMark.max_marks,
            InternalMark.obtained,
        )
        .outerjoin(Course, Course.id == InternalMark.course_id)
        .where(
            InternalMark.tenant_id == tenant_id,
            InternalMark.student_id.in_(student_ids),
            InternalMark.is_deleted.is_(False),
            InternalMark.max_marks > 0,
        )
        .order_by(InternalMark.student_id, InternalMark.created_at, InternalMark.id)
    ).all()

    by_student: dict[UUID, list] = defaultdict(list)
    for row in rows:
        by_student[row.student_id].append(row)

    result: dict[UUID, dict] = {}
    for student_id in student_ids:
        marks = by_student.get(student_id, [])
        pcts = [(row.code, float(row.obtained) / float(row.max_marks) * 100) for row in marks]

        latest_by_course: dict[str, float] = {}
        for course_code, pct in pcts:
            if course_code is not None:
                latest_by_course[course_code] = round(pct, 2)  # later rows overwrite -> latest per course

        failing_internal_count = sum(1 for _, pct in pcts if pct < fail_pct)
        academic_latest_pct = round(pcts[-1][1], 2) if pcts else None
        prior_pcts = [pct for _, pct in pcts[:-1]]
        academic_baseline_pct = round(sum(prior_pcts) / len(prior_pcts), 2) if prior_pcts else None

        result[student_id] = {
            "latest_internal_pct_by_course": tuple(sorted(latest_by_course.items())),
            "failing_internal_count": failing_internal_count,
            "academic_latest_pct": academic_latest_pct,
            "academic_baseline_pct": academic_baseline_pct,
        }
    return result
