import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin


class DataConflict(PKMixin, TenantMixin, Base):
    __tablename__ = "data_conflicts"

    table_name: Mapped[str] = mapped_column(nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field: Mapped[str] = mapped_column(nullable=False)
    existing_value: Mapped[str | None] = mapped_column(nullable=True)
    incoming_value: Mapped[str | None] = mapped_column(nullable=True)
    existing_source: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_systems.id"), nullable=True
    )
    incoming_source: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_systems.id"), nullable=True
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True
    )
    resolved: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=text("false"))
    at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
