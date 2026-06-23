"""Bulk fee-delay signal computation (spec §5.2). One bulk query for the whole
batch of target students.

"unpaid/partially-paid" (spec §5.2) is read off the canonical fees columns
directly, since Phase 1's Fee.status is free-text and not a relied-upon enum:
a fee counts as outstanding when amount_paid is missing or less than
amount_due (decision recorded in CHANGELOG.md).
"""

from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import Fee


def compute_fee_signals(session: Session, tenant_id: UUID, student_ids: list[UUID], config: dict) -> dict[UUID, dict]:
    """Returns, per student_id, max_fee_overdue_days (0 if none overdue)."""
    if not student_ids:
        return {}

    today = date.today()

    rows = session.execute(
        select(Fee.student_id, Fee.due_date, Fee.amount_due, Fee.amount_paid).where(
            Fee.tenant_id == tenant_id,
            Fee.student_id.in_(student_ids),
            Fee.is_deleted.is_(False),
            Fee.due_date.is_not(None),
            Fee.due_date < today,
        )
    ).all()

    max_overdue: dict[UUID, int] = defaultdict(int)
    for row in rows:
        fully_paid = row.amount_paid is not None and row.amount_due is not None and row.amount_paid >= row.amount_due
        if fully_paid:
            continue
        days = (today - row.due_date).days
        if days > max_overdue[row.student_id]:
            max_overdue[row.student_id] = days

    return {student_id: {"max_fee_overdue_days": max_overdue.get(student_id, 0)} for student_id in student_ids}
