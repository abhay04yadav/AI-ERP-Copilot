"""Student Success Engine data model (Phase 2 spec §4).

Mixins and audit wiring reused exactly as Phase 0/1 (see models/__init__.py for
register_audit_hooks calls). Two partial-unique invariants ("exactly one active
config per tenant", "exactly one current assessment per student") are expressed
as partial unique Index objects (postgresql_where) since SQLAlchemy's
UniqueConstraint has no WHERE clause.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, SoftDeleteMixin, TenantMixin, TimestampMixin

MODEL_TYPES = ("rules", "ml")
TIERS = ("low", "watch", "high")
MINOR_STATUSES = ("minor", "adult", "unknown")
TRIGGERED_BY_VALUES = ("import", "manual", "scheduled")
RISK_TYPES = ("attendance", "academic", "fee")
SEVERITIES = ("low", "medium", "high")
INTERVENTION_TYPES = ("mentor_meeting", "remedial_class", "parent_contact", "counselling", "other")
INTERVENTION_STATUSES = ("suggested", "open", "in_progress", "completed", "dismissed")
OUTCOME_VALUES = ("improved", "no_change", "worsened", "unknown")
ALERT_CHANNELS = ("in_app", "email")
ALERT_STATUSES = ("pending", "sent", "read", "suppressed")
FACULTY_SCOPE_TYPES = ("department", "programme", "course", "section")


class RiskConfig(PKMixin, TenantMixin, Base):
    """Per-tenant thresholds, versioned (spec §4.1). Exactly one active row per
    tenant, enforced by a partial unique index on tenant_id WHERE is_active."""

    __tablename__ = "risk_configs"
    __table_args__ = (
        Index("uq_risk_configs_tenant_active", "tenant_id", unique=True, postgresql_where=text("is_active")),
    )

    version: Mapped[int] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class RiskAssessment(PKMixin, TenantMixin, Base):
    """One current assessment per student, full history retained (spec §4.2)."""

    __tablename__ = "risk_assessments"
    __table_args__ = (
        CheckConstraint(f"model_type IN {MODEL_TYPES}", name="ck_risk_assessments_model_type"),
        CheckConstraint(f"tier IN {TIERS}", name="ck_risk_assessments_tier"),
        CheckConstraint(f"subject_minor_status IN {MINOR_STATUSES}", name="ck_risk_assessments_minor_status"),
        CheckConstraint(f"triggered_by IN {TRIGGERED_BY_VALUES}", name="ck_risk_assessments_triggered_by"),
        Index(
            "uq_risk_assessments_tenant_student_current",
            "tenant_id",
            "student_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_risk_assessments_tenant_current_tier", "tenant_id", "is_current", "tier"),
        Index("ix_risk_assessments_tenant_current_score", "tenant_id", "is_current", "overall_score"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    model_type: Mapped[str] = mapped_column(nullable=False)
    model_version: Mapped[str] = mapped_column(nullable=False)
    config_version: Mapped[int] = mapped_column(nullable=False)
    overall_score: Mapped[float] = mapped_column(nullable=False)
    tier: Mapped[str] = mapped_column(nullable=False)
    subject_minor_status: Mapped[str] = mapped_column(nullable=False)
    signals_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    triggered_by: Mapped[str] = mapped_column(nullable=False)
    triggered_by_import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class RiskFinding(PKMixin, TenantMixin, Base):
    """The typed reasons behind an assessment (spec §4.3). Never deleted in
    Phase 2 (history retained for accreditation/ML) — the FK's ON DELETE
    CASCADE is defensive only, since assessments themselves are never deleted."""

    __tablename__ = "risk_findings"
    __table_args__ = (
        CheckConstraint(f"risk_type IN {RISK_TYPES}", name="ck_risk_findings_risk_type"),
        CheckConstraint(f"severity IN {SEVERITIES}", name="ck_risk_findings_severity"),
        Index("ix_risk_findings_tenant_assessment", "tenant_id", "assessment_id"),
        Index("ix_risk_findings_tenant_risk_type", "tenant_id", "risk_type"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_assessments.id", ondelete="CASCADE"), nullable=False
    )
    risk_type: Mapped[str] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(nullable=False)
    severity: Mapped[str] = mapped_column(nullable=False)
    weight_contribution: Mapped[float] = mapped_column(nullable=False)
    message: Mapped[str] = mapped_column(nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Intervention(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    """The human action loop (spec §4.4)."""

    __tablename__ = "interventions"
    __table_args__ = (
        CheckConstraint(f"type IN {INTERVENTION_TYPES}", name="ck_interventions_type"),
        CheckConstraint(f"status IN {INTERVENTION_STATUSES}", name="ck_interventions_status"),
        Index("ix_interventions_tenant_student_status", "tenant_id", "student_id", "status"),
        Index("ix_interventions_tenant_assigned_status", "tenant_id", "assigned_to", "status"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    source_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_assessments.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    guardian_consent_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    """Not named in spec §4.4's column list, but §9 requires recording *who*
    confirmed guardian consent for a minor's parent_contact intervention —
    added to close that gap (CHANGELOG.md)."""


class InterventionOutcome(PKMixin, TenantMixin, Base):
    """Closing the loop; future ML labels (spec §4.5)."""

    __tablename__ = "intervention_outcomes"
    __table_args__ = (CheckConstraint(f"outcome IN {OUTCOME_VALUES}", name="ck_intervention_outcomes_outcome"),)

    intervention_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interventions.id"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(nullable=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class RiskAlert(PKMixin, TenantMixin, Base):
    """Generated in-app notifications (spec §4.6)."""

    __tablename__ = "risk_alerts"
    __table_args__ = (
        CheckConstraint(f"channel IN {ALERT_CHANNELS}", name="ck_risk_alerts_channel"),
        CheckConstraint(f"status IN {ALERT_STATUSES}", name="ck_risk_alerts_status"),
        Index("ix_risk_alerts_tenant_recipient_status", "tenant_id", "recipient_user_id", "status"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_assessments.id"), nullable=True
    )
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(nullable=False, default="in_app", server_default=text("'in_app'"))
    status: Mapped[str] = mapped_column(nullable=False, default="pending", server_default=text("'pending'"))
    reason: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)


class FacultyScope(PKMixin, TenantMixin, Base):
    """What a faculty user is allowed to see (spec §4.7)."""

    __tablename__ = "faculty_scopes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "scope_type", "scope_ref", name="uq_faculty_scopes_natural_key"
        ),
        CheckConstraint(f"scope_type IN {FACULTY_SCOPE_TYPES}", name="ck_faculty_scopes_scope_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    scope_type: Mapped[str] = mapped_column(nullable=False)
    scope_ref: Mapped[str] = mapped_column(nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
