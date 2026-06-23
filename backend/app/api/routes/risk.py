"""Risk engine API surface (spec §13). Reads go through risk_repository
(tenant-scoped + role-scoped); writes go through the services. Role scoping
is always resolved server-side from the verified JWT, never from client
input (spec §14 security)."""

from collections.abc import Sequence
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_tenant_session
from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.models.canonical import Student
from app.models.risk import Intervention, RiskAlert, RiskAssessment, RiskFinding
from app.repositories.risk_repository import RiskRepository
from app.schemas.risk import (
    AlertResponse,
    AtRiskStudentResponse,
    InterventionCreateRequest,
    InterventionOutcomeCreateRequest,
    InterventionOutcomeResponse,
    InterventionResponse,
    InterventionUpdateRequest,
    RecomputeRequest,
    RecomputeSummaryResponse,
    RiskAssessmentResponse,
    RiskConfigResponse,
    RiskConfigUpdateRequest,
    RiskFindingResponse,
    StudentRiskDetailResponse,
)
from app.services.risk import interventions as interventions_service
from app.services.risk.config import get_or_seed_config, set_new_config
from app.services.risk.engine import recompute_for_students, recompute_for_tenant
from app.services.risk.scoping import has_full_visibility, visible_student_ids

router = APIRouter(prefix="/risk", tags=["risk"])


def _ensure_not_student_role(current_user: CurrentUser) -> None:
    if current_user.role == "student":
        raise ForbiddenException("The student role is out of scope for the Student Success Engine (Phase 2).")


def _visible_ids(session: Session, current_user: CurrentUser) -> set[UUID] | None:
    return visible_student_ids(session, current_user.tenant_id, current_user.role, current_user.user_id)


def _assessment_to_response(
    assessment: RiskAssessment, findings: Sequence[RiskFinding]
) -> RiskAssessmentResponse:
    return RiskAssessmentResponse(
        id=assessment.id,
        student_id=assessment.student_id,
        model_type=assessment.model_type,
        model_version=assessment.model_version,
        config_version=assessment.config_version,
        overall_score=float(assessment.overall_score),
        tier=assessment.tier,
        subject_minor_status=assessment.subject_minor_status,
        triggered_by=assessment.triggered_by,
        computed_at=assessment.computed_at,
        findings=[
            RiskFindingResponse(
                risk_type=f.risk_type,
                code=f.code,
                severity=f.severity,
                weight_contribution=float(f.weight_contribution),
                message=f.message,
                evidence=f.evidence,
            )
            for f in findings
        ],
    )


@router.get("/students", response_model=list[AtRiskStudentResponse])
def list_at_risk_students(
    tier: str | None = None,
    risk_type: str | None = None,
    department: str | None = None,
    min_score: float | None = None,
    page: int = Query(default=1, ge=1),
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> list[AtRiskStudentResponse]:
    _ensure_not_student_role(current_user)
    visible = _visible_ids(session, current_user)
    rows = RiskRepository(session, current_user.tenant_id).list_at_risk(
        student_ids=visible, tier=tier, risk_type=risk_type, department=department, min_score=min_score, page=page
    )
    return [
        AtRiskStudentResponse(
            student_id=student.id,
            canonical_roll_no=student.canonical_roll_no,
            name=student.name,
            tier=assessment.tier,
            overall_score=float(assessment.overall_score),
            computed_at=assessment.computed_at,
        )
        for assessment, student in rows
    ]


@router.get("/students/{student_id}", response_model=StudentRiskDetailResponse)
def get_student_risk(
    student_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> StudentRiskDetailResponse:
    _ensure_not_student_role(current_user)
    visible = _visible_ids(session, current_user)
    if visible is not None and student_id not in visible:
        raise NotFoundException("Student not found.")  # don't reveal existence outside the caller's scope

    repo = RiskRepository(session, current_user.tenant_id)
    current = repo.get_current_assessment(student_id)
    if current is None:
        student = session.execute(
            select(Student).where(Student.tenant_id == current_user.tenant_id, Student.id == student_id)
        ).scalar_one_or_none()
        if student is None:
            raise NotFoundException("Student not found.")
        return StudentRiskDetailResponse(student_id=student_id, current=None, history=[], active_interventions=[])

    history = [_assessment_to_response(a, repo.get_findings(a.id)) for a in repo.get_history(student_id)]
    active_interventions = [
        InterventionResponse.model_validate(i, from_attributes=True)
        for i in repo.get_active_interventions(student_id)
    ]
    return StudentRiskDetailResponse(
        student_id=student_id,
        current=_assessment_to_response(current, repo.get_findings(current.id)),
        history=history,
        active_interventions=active_interventions,
    )


@router.post("/recompute", response_model=RecomputeSummaryResponse)
def recompute(
    payload: RecomputeRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> RecomputeSummaryResponse:
    if not has_full_visibility(current_user.role):
        raise ForbiddenException("Only admin/principal/registrar/iqac may trigger a recompute.")

    if payload.scope == "tenant":
        summary = recompute_for_tenant(session, current_user.tenant_id, triggered_by="manual")
    elif payload.scope == "students":
        if not payload.student_ids:
            raise AppException("student_ids is required when scope='students'.")
        summary = recompute_for_students(session, current_user.tenant_id, payload.student_ids, triggered_by="manual")
    else:
        raise AppException("scope must be 'tenant' or 'students'.")

    return RecomputeSummaryResponse(**asdict(summary))


@router.get("/config", response_model=RiskConfigResponse)
def get_config(
    current_user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_tenant_session)
) -> RiskConfigResponse:
    if current_user.role != "admin":
        raise ForbiddenException("Only admin may view the risk config.")
    config_row = get_or_seed_config(session, current_user.tenant_id)
    return RiskConfigResponse(
        id=config_row.id,
        version=config_row.version,
        is_active=config_row.is_active,
        config=config_row.config,
        created_at=config_row.created_at,
    )


@router.put("/config", response_model=RiskConfigResponse)
def update_config(
    payload: RiskConfigUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> RiskConfigResponse:
    if current_user.role != "admin":
        raise ForbiddenException("Only admin may update the risk config.")
    config_row = set_new_config(session, current_user.tenant_id, payload.config, created_by=current_user.user_id)
    return RiskConfigResponse(
        id=config_row.id,
        version=config_row.version,
        is_active=config_row.is_active,
        config=config_row.config,
        created_at=config_row.created_at,
    )


@router.post("/interventions", response_model=InterventionResponse)
def create_intervention(
    payload: InterventionCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> InterventionResponse:
    _ensure_not_student_role(current_user)
    visible = _visible_ids(session, current_user)
    if visible is not None and payload.student_id not in visible:
        raise NotFoundException("Student not found.")

    intervention = interventions_service.create_intervention(
        session,
        current_user.tenant_id,
        student_id=payload.student_id,
        type_=payload.type,
        title=payload.title,
        notes=payload.notes,
        assigned_to=payload.assigned_to,
        created_by=current_user.user_id,
        source_assessment_id=payload.source_assessment_id,
        guardian_consent_confirmed=payload.guardian_consent_confirmed,
    )
    return InterventionResponse.model_validate(intervention, from_attributes=True)


@router.get("/interventions", response_model=list[InterventionResponse])
def list_interventions(
    student_id: UUID | None = None,
    status: str | None = None,
    assigned_to: UUID | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> list[InterventionResponse]:
    _ensure_not_student_role(current_user)
    visible = _visible_ids(session, current_user)
    if visible is not None and not visible:
        return []
    if visible is not None and student_id is not None and student_id not in visible:
        raise NotFoundException("Student not found.")

    query = select(Intervention).where(
        Intervention.tenant_id == current_user.tenant_id, Intervention.is_deleted.is_(False)
    )
    if visible is not None:
        query = query.where(Intervention.student_id.in_(visible))
    if student_id is not None:
        query = query.where(Intervention.student_id == student_id)
    if status is not None:
        query = query.where(Intervention.status == status)
    if assigned_to is not None:
        query = query.where(Intervention.assigned_to == assigned_to)

    rows = session.execute(query.order_by(Intervention.created_at.desc())).scalars().all()
    return [InterventionResponse.model_validate(i, from_attributes=True) for i in rows]


@router.patch("/interventions/{intervention_id}", response_model=InterventionResponse)
def update_intervention(
    intervention_id: UUID,
    payload: InterventionUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> InterventionResponse:
    _ensure_not_student_role(current_user)
    intervention = interventions_service.get_intervention(session, current_user.tenant_id, intervention_id)
    visible = _visible_ids(session, current_user)
    if visible is not None and intervention.student_id not in visible:
        raise NotFoundException("Intervention not found.")

    updated = interventions_service.update_intervention(
        session,
        current_user.tenant_id,
        intervention_id,
        status=payload.status,
        assigned_to=payload.assigned_to,
        notes=payload.notes,
    )
    return InterventionResponse.model_validate(updated, from_attributes=True)


@router.post("/interventions/{intervention_id}/outcome", response_model=InterventionOutcomeResponse)
def create_outcome(
    intervention_id: UUID,
    payload: InterventionOutcomeCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> InterventionOutcomeResponse:
    _ensure_not_student_role(current_user)
    intervention = interventions_service.get_intervention(session, current_user.tenant_id, intervention_id)
    visible = _visible_ids(session, current_user)
    if visible is not None and intervention.student_id not in visible:
        raise NotFoundException("Intervention not found.")

    outcome = interventions_service.record_outcome(
        session,
        current_user.tenant_id,
        intervention_id,
        outcome=payload.outcome,
        notes=payload.notes,
        recorded_by=current_user.user_id,
    )
    return InterventionOutcomeResponse.model_validate(outcome, from_attributes=True)


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(
    status: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> list[AlertResponse]:
    query = select(RiskAlert).where(
        RiskAlert.tenant_id == current_user.tenant_id, RiskAlert.recipient_user_id == current_user.user_id
    )
    if status is not None:
        query = query.where(RiskAlert.status == status)
    rows = session.execute(query.order_by(RiskAlert.created_at.desc())).scalars().all()
    return [AlertResponse.model_validate(a, from_attributes=True) for a in rows]


@router.patch("/alerts/{alert_id}/read", response_model=AlertResponse)
def mark_alert_read(
    alert_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_tenant_session),
) -> AlertResponse:
    alert = session.execute(
        select(RiskAlert).where(
            RiskAlert.tenant_id == current_user.tenant_id,
            RiskAlert.id == alert_id,
            RiskAlert.recipient_user_id == current_user.user_id,
        )
    ).scalar_one_or_none()
    if alert is None:
        raise NotFoundException("Alert not found.")
    alert.status = "read"
    session.flush()
    return AlertResponse.model_validate(alert, from_attributes=True)
