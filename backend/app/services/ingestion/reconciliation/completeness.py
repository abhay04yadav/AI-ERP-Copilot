from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ingestion import StagingRecord
from app.services.ingestion.mapping import ENTITY_CANONICAL_FIELDS


def compute_completeness(session: Session, tenant_id: UUID, import_batch_id: UUID, entity_type: str) -> dict[str, float]:
    """% of this batch's staging rows where each expected canonical field is
    populated (spec §5.8)."""
    rows = (
        session.execute(
            select(StagingRecord.cleaned_payload).where(
                StagingRecord.tenant_id == tenant_id,
                StagingRecord.import_batch_id == import_batch_id,
                StagingRecord.entity_type == entity_type,
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {}

    fields = ENTITY_CANONICAL_FIELDS.get(entity_type, [])
    return {
        field: round(100 * sum(1 for payload in rows if payload.get(field) is not None) / len(rows), 2)
        for field in fields
    }
