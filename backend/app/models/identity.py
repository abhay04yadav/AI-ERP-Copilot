import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin

MATCH_METHODS = ("deterministic", "fuzzy", "manual")
IDENTITY_STATUSES = ("auto_linked", "pending_review", "confirmed", "rejected")
MERGE_REVIEW_STATUSES = ("pending_review", "confirmed", "rejected")


class EntityIdentityMap(PKMixin, TenantMixin, Base):
    __tablename__ = "entity_identity_map"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "entity_type", "source_system_id", "source_id", name="uq_identity_map_natural_key"
        ),
        CheckConstraint(f"match_method IN {MATCH_METHODS}", name="ck_identity_map_match_method"),
        CheckConstraint(f"status IN {IDENTITY_STATUSES}", name="ck_identity_map_status"),
    )

    entity_type: Mapped[str] = mapped_column(nullable=False)
    source_system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_systems.id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(nullable=False)
    canonical_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    match_method: Mapped[str] = mapped_column(nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class MergeReviewItem(PKMixin, TenantMixin, Base):
    """Persisted for human confirmation later (a Phase-2 UI); Phase 1 only
    writes these, never auto-merges them (spec §5.5)."""

    __tablename__ = "merge_review_items"
    __table_args__ = (CheckConstraint(f"status IN {MERGE_REVIEW_STATUSES}", name="ck_merge_review_items_status"),)

    entity_type: Mapped[str] = mapped_column(nullable=False)
    candidate_canonical_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    incoming_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    score: Mapped[Decimal] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="pending_review", server_default=text("'pending_review'"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
