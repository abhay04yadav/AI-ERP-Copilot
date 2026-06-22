import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin

PIPELINE_STATES = (
    "RECEIVED",
    "PARSED",
    "MAPPED",
    "CLEANED",
    "RESOLVED",
    "LOADED",
    "RECONCILED",
    "COMPLETED",
    "FAILED",
)
VALIDATION_STATUSES = ("valid", "quarantined")


class SourceSystem(PKMixin, TenantMixin, Base):
    __tablename__ = "source_systems"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_source_systems_tenant_name"),)

    name: Mapped[str] = mapped_column(nullable=False)
    precedence: Mapped[int] = mapped_column(nullable=False)
    """Lower wins a conflict (spec §5.7's tenant-configurable precedence policy)."""
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class ColumnMapping(PKMixin, TenantMixin, Base):
    __tablename__ = "column_mappings"

    source_system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_systems.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(nullable=False)
    mapping: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class ImportBatch(PKMixin, TenantMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        Index("ix_import_batches_tenant_source_hash", "tenant_id", "source_system_id", "content_hash"),
        CheckConstraint(f"status IN {PIPELINE_STATES}", name="ck_import_batches_status"),
    )

    source_system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_systems.id"), nullable=False
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(nullable=False)
    entity_type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="RECEIVED", server_default=text("'RECEIVED'"))
    row_count_raw: Mapped[int] = mapped_column(nullable=False, default=0, server_default=text("0"))
    row_count_loaded: Mapped[int] = mapped_column(nullable=False, default=0, server_default=text("0"))
    row_count_quarantined: Mapped[int] = mapped_column(nullable=False, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reconciliation_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    """Not in spec §5.2's column list, but §5.8 explicitly requires the DQ
    report to be "persist[ed] + expose[d] via imports.py" — added to close
    that gap (CHANGELOG.md)."""


class RawFile(PKMixin, TenantMixin, Base):
    """Immutable, append-only (spec §5.2) — app_user is granted SELECT/INSERT
    only, never UPDATE, on this table (see migration)."""

    __tablename__ = "raw_files"

    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=False
    )
    storage_uri: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[bytes | None] = mapped_column(nullable=True)
    """Payload for the Postgres-bytea StorageBackend (core/storage.py). Left
    null when a future backend (e.g. S3) is swapped in; storage_uri becomes
    the authoritative pointer at that point."""
    original_filename: Mapped[str] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(nullable=False)
    byte_size: Mapped[int] = mapped_column(nullable=False)


class RawRecord(PKMixin, TenantMixin, Base):
    """Each source row captured verbatim as JSON before any transformation.
    Immutable, append-only (spec §5.2) — same grant restriction as RawFile."""

    __tablename__ = "raw_records"
    __table_args__ = (Index("ix_raw_records_import_batch_id", "import_batch_id"),)

    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class StagingRecord(PKMixin, TenantMixin, Base):
    __tablename__ = "staging_records"
    __table_args__ = (
        Index("ix_staging_records_import_batch_id", "import_batch_id"),
        CheckConstraint(f"validation_status IN {VALIDATION_STATUSES}", name="ck_staging_records_validation_status"),
    )

    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(nullable=False)
    cleaned_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    validation_status: Mapped[str] = mapped_column(nullable=False)
    validation_errors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resolved_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
