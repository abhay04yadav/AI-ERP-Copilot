from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskWeights(BaseModel):
    """Mirrors DEFAULT_RISK_CONFIG["weights"] (spec §6.1). Coupled to rule-set
    v1's five codes -- when a future rule is added, this model must be
    updated alongside it (Phase 2 hardening CHANGE 2)."""

    model_config = ConfigDict(extra="forbid")

    ATTENDANCE_BELOW_THRESHOLD: float = Field(ge=0)
    ATTENDANCE_DECLINING: float = Field(ge=0)
    ACADEMIC_FAILING_INTERNALS: float = Field(ge=0)
    ACADEMIC_DECLINE: float = Field(ge=0)
    FEE_OVERDUE: float = Field(ge=0)


class TierCutoffs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watch: float = Field(ge=0, le=100)
    high: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _watch_below_high(self) -> "TierCutoffs":
        if self.watch >= self.high:
            raise ValueError("tier_cutoffs.watch must be strictly less than high")
        return self


class RiskConfigModel(BaseModel):
    """Validates the shape of risk_configs.config on PUT /risk/config (spec
    §6.1, Phase 2 hardening CHANGE 2) -- a malformed admin update must never
    reach set_new_config and poison every later recompute with a KeyError
    deep in scoring."""

    model_config = ConfigDict(extra="forbid")

    attendance_threshold_pct: float = Field(ge=0, le=100)
    attendance_min_sessions: int = Field(ge=0)
    attendance_trend_window: int = Field(ge=1)
    attendance_decline_points: float = Field(ge=0, le=100)
    academic_fail_pct: float = Field(ge=0, le=100)
    academic_decline_points: float = Field(ge=0, le=100)
    fee_overdue_days: int = Field(ge=0)
    weights: RiskWeights
    tier_cutoffs: TierCutoffs


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


class RiskSummaryByTier(BaseModel):
    high: int
    watch: int
    low: int


class RiskSummaryByType(BaseModel):
    attendance: int
    academic: int
    fee: int


class RiskSummaryResponse(BaseModel):
    total_assessed: int
    by_tier: RiskSummaryByTier
    by_risk_type: RiskSummaryByType
    generated_at: datetime


class DepartmentSummary(BaseModel):
    department: str
    total: int
    high: int
    watch: int
    low: int


class RiskSummaryByDepartmentResponse(BaseModel):
    departments: list[DepartmentSummary]


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
    config: RiskConfigModel


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
