from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RiskFindingResponse(BaseModel):
    risk_type: str
    code: str
    severity: str
    weight_contribution: float
    message: str
    evidence: dict


class RiskAssessmentResponse(BaseModel):
    id: UUID
    student_id: UUID
    model_type: str
    model_version: str
    config_version: int
    overall_score: float
    tier: str
    subject_minor_status: str
    triggered_by: str
    computed_at: datetime
    findings: list[RiskFindingResponse]


class AtRiskStudentResponse(BaseModel):
    student_id: UUID
    canonical_roll_no: str
    name: str
    tier: str
    overall_score: float
    computed_at: datetime


class StudentRiskDetailResponse(BaseModel):
    student_id: UUID
    current: RiskAssessmentResponse | None
    history: list[RiskAssessmentResponse]
    active_interventions: list["InterventionResponse"]


class RecomputeRequest(BaseModel):
    scope: str  # 'tenant' | 'students'
    student_ids: list[UUID] | None = None


class RecomputeSummaryResponse(BaseModel):
    evaluated: int
    changed: int
    unchanged: int
    skipped: int
    errors: list[dict]


class RiskConfigResponse(BaseModel):
    id: UUID
    version: int
    is_active: bool
    config: dict
    created_at: datetime


class RiskConfigUpdateRequest(BaseModel):
    config: dict


class InterventionCreateRequest(BaseModel):
    student_id: UUID
    type: str
    title: str
    notes: str | None = None
    assigned_to: UUID | None = None
    source_assessment_id: UUID | None = None
    guardian_consent_confirmed: bool = False


class InterventionUpdateRequest(BaseModel):
    status: str | None = None
    assigned_to: UUID | None = None
    notes: str | None = None


class InterventionResponse(BaseModel):
    id: UUID
    student_id: UUID
    source_assessment_id: UUID | None
    type: str
    status: str
    title: str
    notes: str | None
    assigned_to: UUID | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class InterventionOutcomeCreateRequest(BaseModel):
    outcome: str
    notes: str | None = None


class InterventionOutcomeResponse(BaseModel):
    id: UUID
    intervention_id: UUID
    outcome: str
    notes: str | None
    recorded_by: UUID | None
    recorded_at: datetime


class AlertResponse(BaseModel):
    id: UUID
    student_id: UUID
    assessment_id: UUID | None
    channel: str
    status: str
    reason: str
    payload: dict
    created_at: datetime
    sent_at: datetime | None


StudentRiskDetailResponse.model_rebuild()
