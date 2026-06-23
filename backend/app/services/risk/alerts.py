"""Alert generation (spec §11). Generated only for material change: a
student newly entering 'high', or escalating watch->high. No alert for
unchanged tier or any de-escalation. Channel in_app only in Phase 2 --
email is a stubbed no-op that stays at status='pending' (spec §16: no real
email/SMS/WhatsApp delivery)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.risk import RiskAlert, RiskAssessment
from app.models.user import User
from app.services.risk.scoping import PRIVILEGED_ROLES, faculty_user_ids_for_student

_MATERIAL_TRANSITIONS = {(None, "high"), ("low", "high"), ("watch", "high")}
"""Spec §11 names two cases explicitly ("newly entering high" and
"escalating watch->high"); a prior tier of 'low' jumping straight to 'high'
is the same "newly entering high" case in substance and included for
completeness (decision recorded in CHANGELOG.md)."""


def generate_alert_if_material(
    session: Session, tenant_id: UUID, student_id: UUID, assessment: RiskAssessment, *, previous_tier: str | None
) -> None:
    if (previous_tier, assessment.tier) not in _MATERIAL_TRANSITIONS:
        return

    reason = "tier_escalated_to_high" if previous_tier == "watch" else "tier_entered_high"
    payload = {
        "student_id": str(student_id),
        "previous_tier": previous_tier,
        "new_tier": assessment.tier,
        "overall_score": float(assessment.overall_score),
    }

    recipient_ids = set(faculty_user_ids_for_student(session, tenant_id, student_id))
    recipient_ids |= set(
        session.execute(
            select(User.id).where(
                User.tenant_id == tenant_id, User.role.in_(PRIVILEGED_ROLES), User.is_active.is_(True)
            )
        ).scalars().all()
    )

    # spec §9 minor/DPDP gate: recipients resolved above are always staff
    # (faculty/principal/registrar/iqac) users -- this function never
    # resolves or creates a parent-directed recipient or channel, regardless
    # of the assessment's subject_minor_status. Phase 2 has no parent-contact
    # alert channel at all (spec §16); if one is ever added, it must gate on
    # subject_minor_status in ('minor', 'unknown') exactly like
    # services/risk/interventions.py's parent_contact gate does.
    for recipient_id in recipient_ids:
        session.add(
            RiskAlert(
                tenant_id=tenant_id,
                student_id=student_id,
                assessment_id=assessment.id,
                recipient_user_id=recipient_id,
                channel="in_app",
                status="pending",
                reason=reason,
                payload=payload,
            )
        )
    session.flush()
