"""Per-tenant risk thresholds (spec §6.1, build step 2). Every threshold/weight/
cutoff used by the rules and scoring layers lives here — never hardcoded
elsewhere (spec §1, §14 "no magic numbers")."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.risk import RiskConfig

DEFAULT_RISK_CONFIG: dict = {
    "attendance_threshold_pct": 75,
    "attendance_min_sessions": 10,
    "attendance_trend_window": 12,
    "attendance_decline_points": 15,
    "academic_fail_pct": 40,
    "academic_decline_points": 15,
    "fee_overdue_days": 30,
    "weights": {
        "ATTENDANCE_BELOW_THRESHOLD": 40,
        "ATTENDANCE_DECLINING": 20,
        "ACADEMIC_FAILING_INTERNALS": 35,
        "ACADEMIC_DECLINE": 20,
        "FEE_OVERDUE": 15,
    },
    "tier_cutoffs": {"watch": 25, "high": 50},
}


def get_or_seed_config(session: Session, tenant_id: UUID) -> RiskConfig:
    """Returns the tenant's active risk_configs row, seeding DEFAULT_RISK_CONFIG
    as version 1 on first use (spec §10.2 step 1: "seed default if none")."""
    existing = session.execute(
        select(RiskConfig).where(RiskConfig.tenant_id == tenant_id, RiskConfig.is_active.is_(True))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    seeded = RiskConfig(tenant_id=tenant_id, version=1, is_active=True, config=DEFAULT_RISK_CONFIG, created_by=None)
    session.add(seeded)
    session.flush()
    return seeded


def set_new_config(session: Session, tenant_id: UUID, config: dict, *, created_by: UUID | None) -> RiskConfig:
    """Updates thresholds -> a new version (spec §13 PUT /risk/config). Never
    mutates a historical config row in place: deactivates the current active
    row and inserts a new one, so old assessments' config_version still
    resolves to the config that actually produced them."""
    current = get_or_seed_config(session, tenant_id)
    current.is_active = False
    new_config = RiskConfig(
        tenant_id=tenant_id, version=current.version + 1, is_active=True, config=config, created_by=created_by
    )
    session.add(new_config)
    session.flush()
    return new_config
