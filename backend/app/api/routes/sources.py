from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_tenant_session
from app.models.ingestion import SourceSystem
from app.schemas.sources import SourceSystemCreate, SourceSystemResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("", response_model=SourceSystemResponse)
def create_source(
    payload: SourceSystemCreate,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> SourceSystem:
    source = SourceSystem(tenant_id=current_user.tenant_id, name=payload.name, precedence=payload.precedence)
    session.add(source)
    session.flush()
    return source


@router.get("", response_model=list[SourceSystemResponse])
def list_sources(
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> list[SourceSystem]:
    return session.execute(
        select(SourceSystem).where(SourceSystem.tenant_id == current_user.tenant_id)
    ).scalars().all()
