"""Tenant-scoped reads for the risk API (spec §3, §13): at-risk list, a
single assessment + findings + history, active interventions. Defense in
depth on top of (not instead of) RLS -- every query below filters by
tenant_id explicitly, same convention as repositories/base.py."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from app.models.canonical import Department, Programme, Student
from app.models.risk import Intervention, RiskAssessment, RiskFinding

_ACTIVE_INTERVENTION_STATUSES = ("suggested", "open", "in_progress")


class RiskRepository:
    def __init__(self, session: Session, tenant_id: UUID):
        self.session = session
        self.tenant_id = tenant_id

    def list_at_risk(
        self,
        *,
        student_ids: set[UUID] | None,
        tier: str | None = None,
        risk_type: str | None = None,
        department: str | None = None,
        min_score: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Sequence[Row[tuple[RiskAssessment, Student]]]:
        if student_ids is not None and not student_ids:
            return []  # role-scoped to nothing visible -- don't even query

        query = (
            select(RiskAssessment, Student)
            .join(Student, Student.id == RiskAssessment.student_id)
            .where(RiskAssessment.tenant_id == self.tenant_id, RiskAssessment.is_current.is_(True))
        )
        if student_ids is not None:
            query = query.where(RiskAssessment.student_id.in_(student_ids))
        if tier is not None:
            query = query.where(RiskAssessment.tier == tier)
        else:
            # "at-risk list" (spec §13's section title) -- every active
            # student gets an assessment, even a 'low'/zero-finding one, so
            # the unfiltered default excludes 'low' rather than returning
            # the whole student body. An explicit tier=low still works for
            # completeness/audit (decision recorded in CHANGELOG.md).
            query = query.where(RiskAssessment.tier != "low")
        if min_score is not None:
            query = query.where(RiskAssessment.overall_score >= min_score)
        if risk_type is not None:
            query = query.where(
                RiskAssessment.id.in_(
                    select(RiskFinding.assessment_id).where(
                        RiskFinding.tenant_id == self.tenant_id, RiskFinding.risk_type == risk_type
                    )
                )
            )
        if department is not None:
            query = (
                query.join(Programme, Programme.id == Student.programme_id)
                .join(Department, Department.id == Programme.department_id)
                .where(Department.code == department)
            )

        query = query.order_by(RiskAssessment.overall_score.desc()).offset((page - 1) * page_size).limit(page_size)
        return self.session.execute(query).all()

    def get_current_assessment(self, student_id: UUID) -> RiskAssessment | None:
        return self.session.execute(
            select(RiskAssessment).where(
                RiskAssessment.tenant_id == self.tenant_id,
                RiskAssessment.student_id == student_id,
                RiskAssessment.is_current.is_(True),
            )
        ).scalar_one_or_none()

    def get_findings(self, assessment_id: UUID) -> Sequence[RiskFinding]:
        return self.session.execute(
            select(RiskFinding).where(
                RiskFinding.tenant_id == self.tenant_id, RiskFinding.assessment_id == assessment_id
            )
        ).scalars().all()

    def get_history(self, student_id: UUID) -> Sequence[RiskAssessment]:
        return self.session.execute(
            select(RiskAssessment)
            .where(RiskAssessment.tenant_id == self.tenant_id, RiskAssessment.student_id == student_id)
            .order_by(RiskAssessment.computed_at.desc())
        ).scalars().all()

    def get_active_interventions(self, student_id: UUID) -> Sequence[Intervention]:
        return self.session.execute(
            select(Intervention).where(
                Intervention.tenant_id == self.tenant_id,
                Intervention.student_id == student_id,
                Intervention.is_deleted.is_(False),
                Intervention.status.in_(_ACTIVE_INTERVENTION_STATUSES),
            )
        ).scalars().all()
