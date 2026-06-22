"""Conflict detection + source-precedence policy (spec §5.7), applied inline
at upsert time — not as a separate post-hoc scan — since that's the only
point where "existing value" and "incoming value" are both in hand."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.conflict import DataConflict
from app.models.ingestion import SourceSystem


def get_precedence(session: Session, source_system_id: UUID | None) -> float:
    """Lower number wins (SourceSystem.precedence). Untracked source -> treated
    as lowest priority so any tracked incoming source can establish a value."""
    if source_system_id is None:
        return float("inf")
    source = session.get(SourceSystem, source_system_id)
    return source.precedence if source is not None else float("inf")


def apply_field_with_precedence(
    session: Session,
    *,
    entity,
    field: str,
    incoming_value,
    table_name: str,
    tenant_id: UUID,
    import_batch_id: UUID | None,
    existing_source_id: UUID | None,
    incoming_source_id: UUID,
) -> None:
    """Mutates entity.<field> in place. Higher-precedence (lower number)
    source wins; equal precedence + different value -> keep current, write a
    DataConflict row, never silently clobber (spec §5.7)."""
    existing_value = getattr(entity, field)
    if incoming_value is None or incoming_value == existing_value:
        return

    if existing_value is None or existing_source_id == incoming_source_id:
        # A later import from the exact same source supersedes its own
        # earlier import (e.g. a corrected re-upload) — the precedence
        # policy is for reconciling *different* sources disagreeing, not a
        # source conflicting with its own previous extract.
        setattr(entity, field, incoming_value)
        return

    existing_precedence = get_precedence(session, existing_source_id)
    incoming_precedence = get_precedence(session, incoming_source_id)

    if incoming_precedence < existing_precedence:
        setattr(entity, field, incoming_value)
    elif incoming_precedence == existing_precedence:
        session.add(
            DataConflict(
                tenant_id=tenant_id,
                table_name=table_name,
                record_id=entity.id,
                field=field,
                existing_value=str(existing_value),
                incoming_value=str(incoming_value),
                existing_source=existing_source_id,
                incoming_source=incoming_source_id,
                import_batch_id=import_batch_id,
                resolved=False,
            )
        )
    # else incoming has lower precedence (higher number): keep current, no-op.
