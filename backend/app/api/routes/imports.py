from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_tenant_session
from app.core.exceptions import NotFoundException
from app.models.ingestion import ImportBatch, StagingRecord
from app.schemas.imports import ImportBatchResponse, QuarantineRowResponse
from app.services.ingestion.parsing import compute_content_hash
from app.services.ingestion.pipeline import run_pipeline

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("", response_model=ImportBatchResponse)
async def create_import(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    source_system_id: UUID = Form(...),
    entity_type: str = Form(...),
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> ImportBatch:
    content = await file.read()
    content_hash = compute_content_hash(content)

    existing = session.execute(
        select(ImportBatch).where(
            ImportBatch.tenant_id == current_user.tenant_id,
            ImportBatch.source_system_id == source_system_id,
            ImportBatch.content_hash == content_hash,
        )
    ).scalars().first()
    if existing is not None:
        return existing  # idempotent upload (spec §5.2) — don't re-create raw rows

    batch = ImportBatch(
        tenant_id=current_user.tenant_id,
        source_system_id=source_system_id,
        uploaded_by=current_user.user_id,
        original_filename=file.filename,
        content_hash=content_hash,
        entity_type=entity_type,
        status="RECEIVED",
    )
    session.add(batch)
    session.flush()

    # Captured before the background task runs (it gets its own session/transaction,
    # opened only after this request's session commits — FastAPI runs background
    # tasks after the response, i.e. after get_tenant_session's commit).
    background_tasks.add_task(run_pipeline, current_user.tenant_id, batch.id, content, current_user.user_id)
    return batch


@router.get("/{import_batch_id}", response_model=ImportBatchResponse)
def get_import(
    import_batch_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> ImportBatch:
    batch = session.execute(
        select(ImportBatch).where(ImportBatch.tenant_id == current_user.tenant_id, ImportBatch.id == import_batch_id)
    ).scalar_one_or_none()
    if batch is None:
        raise NotFoundException("Import batch not found.")
    return batch


@router.get("/{import_batch_id}/quarantine", response_model=list[QuarantineRowResponse])
def get_quarantine(
    import_batch_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> list[StagingRecord]:
    return session.execute(
        select(StagingRecord).where(
            StagingRecord.tenant_id == current_user.tenant_id,
            StagingRecord.import_batch_id == import_batch_id,
            StagingRecord.validation_status == "quarantined",
        )
    ).scalars().all()
