from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_tenant_session
from app.models.ingestion import ColumnMapping
from app.schemas.mappings import (
    ColumnMappingCreate,
    ColumnMappingResponse,
    MappingSuggestRequest,
    MappingSuggestResponse,
)
from app.services.ingestion.mapping import suggest_mapping

router = APIRouter(prefix="/mappings", tags=["mappings"])


@router.post("", response_model=ColumnMappingResponse)
def create_mapping(
    payload: ColumnMappingCreate,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> ColumnMapping:
    """Mappings are saved and reused per source+entity (spec §5.3) — each
    POST adds a new version rather than overwriting, so a past import batch's
    mapping is always reconstructable."""
    latest_version = session.execute(
        select(ColumnMapping.version)
        .where(
            ColumnMapping.tenant_id == current_user.tenant_id,
            ColumnMapping.source_system_id == payload.source_system_id,
            ColumnMapping.entity_type == payload.entity_type,
        )
        .order_by(ColumnMapping.version.desc())
    ).scalars().first()

    mapping = ColumnMapping(
        tenant_id=current_user.tenant_id,
        source_system_id=payload.source_system_id,
        entity_type=payload.entity_type,
        mapping=payload.mapping,
        version=(latest_version or 0) + 1,
    )
    session.add(mapping)
    session.flush()
    return mapping


@router.get("", response_model=list[ColumnMappingResponse])
def list_mappings(
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> list[ColumnMapping]:
    return session.execute(
        select(ColumnMapping).where(ColumnMapping.tenant_id == current_user.tenant_id)
    ).scalars().all()


@router.post("/suggest", response_model=MappingSuggestResponse)
def suggest(
    payload: MappingSuggestRequest, current_user: CurrentUser = Depends(get_current_user)
) -> MappingSuggestResponse:
    """Fuzzy header->canonical-field suggestion the user confirms before it's
    saved as a ColumnMapping (spec §5.3) — never auto-applied, so no DB write."""
    return MappingSuggestResponse(suggestions=suggest_mapping(payload.headers, payload.entity_type))
