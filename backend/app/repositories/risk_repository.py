"""Tenant-scoped reads for the risk API (spec §3, §13): at-risk list, a
single assessment + findings + history, active interventions. Defense in
depth on top of (not instead of) RLS -- every query below filters by
tenant_id explicitly, same convention as repositories/base.py."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.models.canonical import Department, Programme, Student
from app.models.risk import RISK_TYPES, TIERS, Intervention, RiskAssessment, RiskFinding

_ACTIVE_INTERVENTION_STATUSES = ("suggested", "open", "in_progress")
_UNASSIGNED_DEPARTMENT = "Unassigned"


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

    def summary(self, *, student_ids: set[UUID] | None) -> dict:
        """Tile/distribution-bar data for the dashboard (Phase 3 spec §A.2).
        Two bulk aggregate queries total, regardless of student count --
        never a per-student loop."""
        by_tier = dict.fromkeys(TIERS, 0)
        by_risk_type = dict.fromkeys(RISK_TYPES, 0)
        if student_ids is not None and not student_ids:
            return {"total_assessed": 0, "by_tier": by_tier, "by_risk_type": by_risk_type}

        tier_query = select(RiskAssessment.tier, func.count()).where(
            RiskAssessment.tenant_id == self.tenant_id, RiskAssessment.is_current.is_(True)
        )
        if student_ids is not None:
            tier_query = tier_query.where(RiskAssessment.student_id.in_(student_ids))
        tier_query = tier_query.group_by(RiskAssessment.tier)
        for tier, count in self.session.execute(tier_query).all():
            by_tier[tier] = count
        total_assessed = sum(by_tier.values())

        # by_risk_type counts *distinct visible students* with >=1 current
        # finding of that type (spec: "a student may count under several
        # types") -- not a finding count, so distinct() on student_id.
        type_query = (
            select(RiskFinding.risk_type, func.count(func.distinct(RiskAssessment.student_id)))
            .join(RiskAssessment, RiskAssessment.id == RiskFinding.assessment_id)
            .where(
                RiskAssessment.tenant_id == self.tenant_id,
                RiskAssessment.is_current.is_(True),
                RiskFinding.tenant_id == self.tenant_id,
            )
        )
        if student_ids is not None:
            type_query = type_query.where(RiskAssessment.student_id.in_(student_ids))
        type_query = type_query.group_by(RiskFinding.risk_type)
        for risk_type, count in self.session.execute(type_query).all():
            by_risk_type[risk_type] = count

        return {"total_assessed": total_assessed, "by_tier": by_tier, "by_risk_type": by_risk_type}

    def summary_by_department(self, *, student_ids: set[UUID] | None) -> list[dict]:
        """Dashboard "by department" tiles (Phase 3 spec §A.3). One bulk
        aggregate query, grouped by department code; students with no
        resolvable department (no programme, or programme with no
        department) fall into the "Unassigned" bucket (spec: never the same
        as "no mentor" -- see CHANGELOG.md)."""
        if student_ids is not None and not student_ids:
            return []

        department_label = func.coalesce(Department.code, _UNASSIGNED_DEPARTMENT).label("department")
        query = (
            select(department_label, RiskAssessment.tier, func.count())
            .select_from(RiskAssessment)
            .join(Student, Student.id == RiskAssessment.student_id)
            .outerjoin(Programme, Programme.id == Student.programme_id)
            .outerjoin(Department, Department.id == Programme.department_id)
            .where(RiskAssessment.tenant_id == self.tenant_id, RiskAssessment.is_current.is_(True))
        )
        if student_ids is not None:
            query = query.where(RiskAssessment.student_id.in_(student_ids))
        query = query.group_by(department_label, RiskAssessment.tier)

        by_department: dict[str, dict[str, int]] = {}
        for department, tier, count in self.session.execute(query).all():
            by_department.setdefault(department, dict.fromkeys(TIERS, 0))[tier] = count

        return [
            {"department": department, "total": sum(tiers.values()), **tiers}
            for department, tiers in sorted(by_department.items())
        ]
