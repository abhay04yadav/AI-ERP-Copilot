"""Pipeline state machine (spec §5.1):

  RECEIVED -> PARSED -> MAPPED -> CLEANED -> RESOLVED -> LOADED -> RECONCILED -> COMPLETED
                                                   \\-(unrecoverable)-> FAILED

Three transaction boundaries, not one, because raw/staging data must survive
even if loading later fails (spec §1: raw layer is immutable/append-only; "no
data loss" applies to quarantined rows too) — only the canonical write must
roll back atomically on failure (spec §5.6, acceptance test §9.5):

  1. parse:   RECEIVED -> PARSED        (raw_files, raw_records)
  2. clean:   MAPPED -> CLEANED         (staging_records, valid or quarantined)
  3. load:    RESOLVED -> LOADED        (canonical upserts; per-row reference
              failures are caught and quarantine that row without aborting
              the transaction; any *other* exception aborts the whole
              transaction -> batch FAILED, canonical untouched)
  4. reconcile: RECONCILED -> COMPLETED (persist the DQ report)

Runs as a FastAPI background task (spec §2: in-process for Phase 1) — it
opens its own session since it executes outside any request's session.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.rls import set_tenant_context
from app.core.storage import get_storage_backend
from app.models.ingestion import ColumnMapping, ImportBatch, RawRecord, StagingRecord
from app.services.ingestion.cleaning.normalizers import clean_payload
from app.services.ingestion.cleaning.validators import validate_record
from app.services.ingestion.connectors.csv_excel import CsvExcelConnector
from app.services.ingestion.loading import canonical_loader
from app.services.ingestion.mapping import apply_mapping
from app.services.ingestion.parsing import parse_raw_records, store_raw_file
from app.services.ingestion.reconciliation.anomalies import detect_anomalies
from app.services.ingestion.reconciliation.completeness import compute_completeness
from app.services.ingestion.resolution.resolver import resolve_student

logger = logging.getLogger(__name__)

_SIMPLE_LOADERS = {
    "department": canonical_loader.upsert_department,
    "programme": canonical_loader.upsert_programme,
    "course": canonical_loader.upsert_course,
    "enrollment": canonical_loader.upsert_enrollment,
    "attendance": canonical_loader.upsert_attendance,
    "internal_mark": canonical_loader.upsert_internal_mark,
    "fee": canonical_loader.upsert_fee,
}
SUPPORTED_ENTITY_TYPES = frozenset({"student", *_SIMPLE_LOADERS})


def run_pipeline(tenant_id: UUID, import_batch_id: UUID, content: bytes) -> None:
    """Runs as a FastAPI BackgroundTask, which Starlette does not shield from
    exceptions — letting one escape here would propagate into (and crash) the
    ASGI response cycle that's already been sent. The batch's FAILED status +
    error message in the DB is the actual signal clients observe (via GET
    /imports/{id}), so failures are logged, not re-raised."""
    session = SessionLocal()
    try:
        _phase_parse(session, tenant_id, import_batch_id, content)
        _phase_clean(session, tenant_id, import_batch_id)
        _phase_resolve_and_load(session, tenant_id, import_batch_id)
        _phase_reconcile(session, tenant_id, import_batch_id)
    except Exception as exc:  # noqa: BLE001 - any unhandled failure marks the batch FAILED
        logger.exception("Ingestion pipeline failed for import_batch_id=%s", import_batch_id)
        _mark_failed(tenant_id, import_batch_id, str(exc))
    finally:
        session.close()


def _phase_parse(session: Session, tenant_id: UUID, import_batch_id: UUID, content: bytes) -> None:
    with session.begin():
        set_tenant_context(session, tenant_id)
        batch = session.get(ImportBatch, import_batch_id)
        batch.status = "RECEIVED"
        batch.started_at = datetime.now(timezone.utc)

        connector = CsvExcelConnector(batch.original_filename)
        storage = get_storage_backend()
        store_raw_file(session, storage, batch, content, batch.original_filename, batch.content_hash)
        batch.row_count_raw = parse_raw_records(session, batch, connector, content)
        batch.status = "PARSED"


def _phase_clean(session: Session, tenant_id: UUID, import_batch_id: UUID) -> None:
    with session.begin():
        set_tenant_context(session, tenant_id)
        batch = session.get(ImportBatch, import_batch_id)
        batch.status = "MAPPED"

        mapping_row = session.execute(
            select(ColumnMapping)
            .where(
                ColumnMapping.tenant_id == tenant_id,
                ColumnMapping.source_system_id == batch.source_system_id,
                ColumnMapping.entity_type == batch.entity_type,
            )
            .order_by(ColumnMapping.version.desc())
        ).scalars().first()
        if mapping_row is None:
            raise ValueError(
                f"no column mapping for source_system={batch.source_system_id} entity_type={batch.entity_type}"
            )

        raw_records = session.execute(
            select(RawRecord).where(RawRecord.tenant_id == tenant_id, RawRecord.import_batch_id == import_batch_id)
        ).scalars().all()

        quarantined = 0
        for raw_record in raw_records:
            mapped = apply_mapping(raw_record.raw_payload, mapping_row.mapping)
            cleaned = clean_payload(batch.entity_type, mapped)
            errors = validate_record(batch.entity_type, cleaned)
            if errors:
                quarantined += 1
            session.add(
                StagingRecord(
                    tenant_id=tenant_id,
                    import_batch_id=import_batch_id,
                    entity_type=batch.entity_type,
                    cleaned_payload=cleaned,
                    validation_status="quarantined" if errors else "valid",
                    validation_errors={"errors": errors} if errors else None,
                )
            )

        batch.row_count_quarantined = quarantined
        batch.status = "CLEANED"


def _phase_resolve_and_load(session: Session, tenant_id: UUID, import_batch_id: UUID) -> None:
    with session.begin():
        set_tenant_context(session, tenant_id)
        batch = session.get(ImportBatch, import_batch_id)
        batch.status = "RESOLVED"

        if batch.entity_type not in SUPPORTED_ENTITY_TYPES:
            raise ValueError(f"unsupported entity_type: {batch.entity_type}")

        staging_rows = session.execute(
            select(StagingRecord).where(
                StagingRecord.tenant_id == tenant_id,
                StagingRecord.import_batch_id == import_batch_id,
                StagingRecord.validation_status == "valid",
            )
        ).scalars().all()

        loaded = 0
        newly_quarantined = 0
        for staging_row in staging_rows:
            provenance = {
                "source_system_id": batch.source_system_id,
                "source_record_id": str(staging_row.id),
                "import_batch_id": import_batch_id,
            }
            try:
                if batch.entity_type == "student":
                    resolution = resolve_student(
                        session, tenant_id, batch.source_system_id, staging_row.cleaned_payload
                    )
                    entity = canonical_loader.upsert_student(
                        session, tenant_id, staging_row.cleaned_payload, provenance, resolution
                    )
                    if entity is None:
                        continue  # pending_review: stays "valid" but unresolved, not loaded
                else:
                    entity = _SIMPLE_LOADERS[batch.entity_type](
                        session, tenant_id, staging_row.cleaned_payload, provenance
                    )
                staging_row.resolved_entity_id = entity.id
                loaded += 1
            except canonical_loader.UnresolvedReferenceError as exc:
                staging_row.validation_status = "quarantined"
                staging_row.validation_errors = {"errors": [str(exc)]}
                newly_quarantined += 1

        batch.row_count_loaded = loaded
        batch.row_count_quarantined += newly_quarantined
        batch.status = "LOADED"


def _phase_reconcile(session: Session, tenant_id: UUID, import_batch_id: UUID) -> None:
    with session.begin():
        set_tenant_context(session, tenant_id)
        batch = session.get(ImportBatch, import_batch_id)
        batch.status = "RECONCILED"

        valid_count = batch.row_count_raw - batch.row_count_quarantined
        batch.reconciliation_report = {
            "raw_count": batch.row_count_raw,
            "valid_count": valid_count,
            "quarantined_count": batch.row_count_quarantined,
            "loaded_count": batch.row_count_loaded,
            "no_op_or_pending_review_count": valid_count - batch.row_count_loaded,
            "anomalies": detect_anomalies(session, tenant_id, import_batch_id),
            "completeness": compute_completeness(session, tenant_id, import_batch_id, batch.entity_type),
        }

        batch.status = "COMPLETED"
        batch.finished_at = datetime.now(timezone.utc)


def _mark_failed(tenant_id: UUID, import_batch_id: UUID, error: str) -> None:
    session = SessionLocal()
    try:
        with session.begin():
            set_tenant_context(session, tenant_id)
            batch = session.get(ImportBatch, import_batch_id)
            batch.status = "FAILED"
            batch.error = error
            batch.finished_at = datetime.now(timezone.utc)
    finally:
        session.close()
