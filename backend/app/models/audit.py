import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin

VALID_ACTIONS = ("insert", "update", "soft_delete")


class AuditLog(PKMixin, TenantMixin, Base):
    """Append-only. No update/delete on this table, ever — enforced by convention
    (no repository update/delete method is implemented for it) and revisited as a
    DB-level REVOKE once the app_user grants are finalized."""

    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint(f"action IN {VALID_ACTIONS}", name="ck_audit_log_action"),)

    table_name: Mapped[str] = mapped_column(nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
