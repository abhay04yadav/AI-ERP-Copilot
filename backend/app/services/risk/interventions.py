"""Intervention lifecycle service: suggest/assign/complete/outcome (spec
§4.4, §13). Advisory only -- the engine never auto-takes an adverse action,
and this module never auto-creates a parent_contact intervention for a
minor/unknown subject (spec §9 hard gate, enforced below)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.risk import Intervention, InterventionOutcome, RiskAssessment

PARENT_CONTACT_TYPE = "parent_contact"


def _current_minor_status(session: Session, tenant_id: UUID, student_id: UUID) -> str:
    status = session.execute(
        select(RiskAssessment.subject_minor_status).where(
            RiskAssessment.tenant_id == tenant_id,
            RiskAssessment.student_id == student_id,
            RiskAssessment.is_current.is_(True),
        )
    ).scalar_one_or_none()
    return status if status is not None else "unknown"


def create_intervention(
    session: Session,
    tenant_id: UUID,
    *,
    student_id: UUID,
    type_: str,
    title: str,
    notes: str | None,
    assigned_to: UUID | None,
    created_by: UUID | None,
    source_assessment_id: UUID | None,
    guardian_consent_confirmed: bool,
) -> Intervention:
    guardian_consent_confirmed_by = None
    if type_ == PARENT_CONTACT_TYPE:
        # spec §9 hard gate: a parent_contact intervention for a minor or
        # unknown-dob subject is never auto-created/auto-suggested, and a
        # manual one requires an explicit, human-confirmed consent flag on
        # this exact request -- the confirming user is recorded. Non-parent
        # interventions (mentor_meeting, remedial_class, counselling, other)
        # are unrestricted. A legal review precedes any change here.
        minor_status = _current_minor_status(session, tenant_id, student_id)
        if minor_status in ("minor", "unknown"):
            if not guardian_consent_confirmed:
                raise ForbiddenException(
                    "parent_contact for a minor/unknown-dob student requires guardian_consent_confirmed=true."
                )
            guardian_consent_confirmed_by = created_by

    intervention = Intervention(
        tenant_id=tenant_id,
        student_id=student_id,
        source_assessment_id=source_assessment_id,
        type=type_,
        status="suggested",
        title=title,
        notes=notes,
        assigned_to=assigned_to,
        created_by=created_by,
        guardian_consent_confirmed_by=guardian_consent_confirmed_by,
    )
    session.add(intervention)
    session.flush()
    return intervention


def get_intervention(session: Session, tenant_id: UUID, intervention_id: UUID) -> Intervention:
    intervention = session.execute(
        select(Intervention).where(Intervention.tenant_id == tenant_id, Intervention.id == intervention_id)
    ).scalar_one_or_none()
    if intervention is None:
        raise NotFoundException("Intervention not found.")
    return intervention


def update_intervention(
    session: Session,
    tenant_id: UUID,
    intervention_id: UUID,
    *,
    status: str | None,
    assigned_to: UUID | None,
    notes: str | None,
) -> Intervention:
    intervention = get_intervention(session, tenant_id, intervention_id)
    if status is not None:
        intervention.status = status
    if assigned_to is not None:
        intervention.assigned_to = assigned_to
    if notes is not None:
        intervention.notes = notes
    session.flush()
    return intervention


def record_outcome(
    session: Session,
    tenant_id: UUID,
    intervention_id: UUID,
    *,
    outcome: str,
    notes: str | None,
    recorded_by: UUID | None,
) -> InterventionOutcome:
    get_intervention(session, tenant_id, intervention_id)  # 404s if missing/wrong tenant
    record = InterventionOutcome(
        tenant_id=tenant_id,
        intervention_id=intervention_id,
        outcome=outcome,
        notes=notes,
        recorded_by=recorded_by,
    )
    session.add(record)
    session.flush()
    return record
