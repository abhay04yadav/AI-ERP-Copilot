from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import EntityIdentityMap


def get_existing_link(
    session: Session, tenant_id: UUID, entity_type: str, source_system_id: UUID, source_id: str
) -> EntityIdentityMap | None:
    stmt = select(EntityIdentityMap).where(
        EntityIdentityMap.tenant_id == tenant_id,
        EntityIdentityMap.entity_type == entity_type,
        EntityIdentityMap.source_system_id == source_system_id,
        EntityIdentityMap.source_id == source_id,
    )
    return session.execute(stmt).scalar_one_or_none()


def write_link(
    session: Session,
    *,
    tenant_id: UUID,
    entity_type: str,
    source_system_id: UUID,
    source_id: str,
    canonical_id: UUID,
    match_method: str,
    confidence,
    status: str,
) -> EntityIdentityMap:
    link = EntityIdentityMap(
        tenant_id=tenant_id,
        entity_type=entity_type,
        source_system_id=source_system_id,
        source_id=source_id,
        canonical_id=canonical_id,
        match_method=match_method,
        confidence=confidence,
        status=status,
    )
    session.add(link)
    session.flush()
    return link
