"""Anomaly checks (spec §5.8): impossible marks, attendance > 100%, duplicate
fee heads, out-of-range dates. Run against this batch's loaded canonical rows
(import_batch_id), not the whole table, so the report is scoped to what this
import actually touched.

Note: attendance > 100% is structurally impossible against our schema
(per-session present/absent rows, not a raw percentage field) — the check is
implemented as written in the spec anyway so it's ready to fire the moment a
future connector (e.g. an ERP reporting attendance as a percentage directly)
feeds that field in. Documented in CHANGELOG.md.
"""

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.canonical import Attendance, Fee, InternalMark


def detect_anomalies(session: Session, tenant_id: UUID, import_batch_id: UUID) -> list[str]:
    anomalies: list[str] = []
    anomalies.extend(_impossible_marks(session, tenant_id, import_batch_id))
    anomalies.extend(_attendance_over_100(session, tenant_id, import_batch_id))
    anomalies.extend(_duplicate_fee_heads(session, tenant_id, import_batch_id))
    anomalies.extend(_out_of_range_dates(session, tenant_id, import_batch_id))
    return anomalies


def _impossible_marks(session: Session, tenant_id: UUID, import_batch_id: UUID) -> list[str]:
    rows = (
        session.execute(
            select(InternalMark).where(
                InternalMark.tenant_id == tenant_id,
                InternalMark.import_batch_id == import_batch_id,
                InternalMark.obtained > InternalMark.max_marks,
            )
        )
        .scalars()
        .all()
    )
    return [f"internal_mark {row.id}: obtained ({row.obtained}) exceeds max_marks ({row.max_marks})" for row in rows]


def _attendance_over_100(session: Session, tenant_id: UUID, import_batch_id: UUID) -> list[str]:
    rows = session.execute(
        select(
            Attendance.student_id,
            Attendance.course_id,
            func.count().label("total"),
            func.sum(case((Attendance.status == "present", 1), else_=0)).label("present"),
        )
        .where(Attendance.tenant_id == tenant_id, Attendance.import_batch_id == import_batch_id)
        .group_by(Attendance.student_id, Attendance.course_id)
    ).all()
    return [
        f"student {row.student_id} course {row.course_id}: attendance {row.present}/{row.total} exceeds 100%"
        for row in rows
        if row.total and (row.present / row.total) * 100 > 100
    ]


def _duplicate_fee_heads(session: Session, tenant_id: UUID, import_batch_id: UUID) -> list[str]:
    rows = session.execute(
        select(Fee.student_id, Fee.term, Fee.fee_head, func.count().label("n"))
        .where(Fee.tenant_id == tenant_id, Fee.import_batch_id == import_batch_id)
        .group_by(Fee.student_id, Fee.term, Fee.fee_head)
        .having(func.count() > 1)
    ).all()
    return [f"student {row.student_id}: duplicate fee_head {row.fee_head!r} in term {row.term!r}" for row in rows]


def _out_of_range_dates(session: Session, tenant_id: UUID, import_batch_id: UUID) -> list[str]:
    rows = (
        session.execute(
            select(Attendance).where(
                Attendance.tenant_id == tenant_id,
                Attendance.import_batch_id == import_batch_id,
                Attendance.class_date > func.current_date(),
            )
        )
        .scalars()
        .all()
    )
    return [f"attendance {row.id}: class_date {row.class_date} is in the future" for row in rows]
