"""Recompute orchestrator (spec §10). Bulk-computes signals once per batch of
target students (never a per-student round trip, spec §1/§14), evaluates each
student through RulesRiskEvaluator, and persists idempotently: identical
inputs produce no new assessment row, changed inputs supersede + insert.

This module never opens its own outer transaction -- exactly like
auth_service.py / canonical_loader.py, it operates on whatever transaction
the caller already has open (the API's get_tenant_session dependency, or the
pipeline hook's own session/transaction, spec §10.3). Per-student writes are
wrapped in a SAVEPOINT (session.begin_nested()) so one student's failure
during evaluation or persist is caught and recorded without aborting the
rest of the batch (spec §10.2 step 5, "mirrors Phase 1's per-row quarantine
philosophy").
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rls import set_tenant_context
from app.models.canonical import Attendance, Enrollment, Fee, InternalMark, Student
from app.models.ingestion import ImportBatch, StagingRecord
from app.models.risk import RiskAssessment, RiskFinding
from app.services.risk.alerts import generate_alert_if_material
from app.services.risk.config import get_or_seed_config
from app.services.risk.evaluator.base import AssessmentResult
from app.services.risk.evaluator.rules_evaluator import RulesRiskEvaluator
from app.services.risk.signals.academic import compute_academic_signals
from app.services.risk.signals.attendance import compute_attendance_signals
from app.services.risk.signals.base import StudentSignals, signals_to_jsonable
from app.services.risk.signals.fees import compute_fee_signals

logger = logging.getLogger(__name__)

_RISK_RELEVANT_ENTITY_TYPES = ("student", "attendance", "internal_mark", "fee", "enrollment")
_ENTITY_MODEL_BY_TYPE = {
    "attendance": Attendance,
    "internal_mark": InternalMark,
    "fee": Fee,
    "enrollment": Enrollment,
}

_evaluator = RulesRiskEvaluator()


@dataclass
class RecomputeSummary:
    evaluated: int = 0
    changed: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)


def compute_subject_minor_status(dob: date | None, computed_at: date) -> str:
    """spec §9 (DPDP): a "child" is anyone under 18 at computed_at. This
    status gates parent_contact interventions (services/risk/interventions.py)
    and parent-directed alerts (services/risk/alerts.py) -- see those gates
    for the actual enforcement points. A legal review precedes any change
    that would make minor-profiling non-advisory."""
    if dob is None:
        return "unknown"
    age_years = computed_at.year - dob.year - ((computed_at.month, computed_at.day) < (dob.month, dob.day))
    return "minor" if age_years < 18 else "adult"


def _bulk_compute_signals(
    session: Session, tenant_id: UUID, student_ids: list[UUID], config: dict
) -> dict[UUID, StudentSignals]:
    """The bulk aggregate read phase (spec §5/§10.2 step 2): a fixed, small
    number of queries regardless of len(student_ids)."""
    attendance = compute_attendance_signals(session, tenant_id, student_ids, config)
    academic = compute_academic_signals(session, tenant_id, student_ids, config)
    fees = compute_fee_signals(session, tenant_id, student_ids, config)

    dob_rows = session.execute(
        select(Student.id, Student.dob).where(
            Student.tenant_id == tenant_id, Student.id.in_(student_ids), Student.is_deleted.is_(False)
        )
    ).all()
    dob_by_student = {row.id: row.dob for row in dob_rows}

    signals_map: dict[UUID, StudentSignals] = {}
    for student_id in student_ids:
        if student_id not in dob_by_student:
            continue  # not a real/visible student in this tenant -- skipped, not an error
        a = attendance.get(student_id, {})
        ac = academic.get(student_id, {})
        f = fees.get(student_id, {})
        signals_map[student_id] = StudentSignals(
            student_id=student_id,
            dob=dob_by_student[student_id],
            overall_attendance_pct=a.get("overall_attendance_pct"),
            overall_sessions=a.get("overall_sessions", 0),
            attendance_by_course=a.get("attendance_by_course", ()),
            attendance_recent_pct=a.get("attendance_recent_pct"),
            attendance_prior_pct=a.get("attendance_prior_pct"),
            latest_internal_pct_by_course=ac.get("latest_internal_pct_by_course", ()),
            failing_internal_count=ac.get("failing_internal_count", 0),
            academic_latest_pct=ac.get("academic_latest_pct"),
            academic_baseline_pct=ac.get("academic_baseline_pct"),
            max_fee_overdue_days=f.get("max_fee_overdue_days", 0),
        )
    return signals_map


def _result_signature(result: AssessmentResult) -> tuple:
    return (result.tier, float(result.overall_score), frozenset((f.code, float(f.weight_contribution)) for f in result.findings))


def _current_assessment_and_signature(
    session: Session, tenant_id: UUID, student_id: UUID
) -> tuple[RiskAssessment | None, tuple | None]:
    current = session.execute(
        select(RiskAssessment).where(
            RiskAssessment.tenant_id == tenant_id,
            RiskAssessment.student_id == student_id,
            RiskAssessment.is_current.is_(True),
        )
    ).scalar_one_or_none()
    if current is None:
        return None, None

    finding_rows = session.execute(
        select(RiskFinding.code, RiskFinding.weight_contribution).where(
            RiskFinding.tenant_id == tenant_id, RiskFinding.assessment_id == current.id
        )
    ).all()
    signature = (
        current.tier,
        float(current.overall_score),
        frozenset((row.code, float(row.weight_contribution)) for row in finding_rows),
    )
    return current, signature


def _persist_one(
    session: Session,
    tenant_id: UUID,
    student_id: UUID,
    signals: StudentSignals,
    config_row,
    triggered_by: str,
    import_batch_id: UUID | None,
) -> str:
    """Returns 'changed' or 'unchanged'. Any exception propagates to the
    caller's per-student savepoint, which isolates it (spec §10.2 step 5)."""
    result = _evaluator.evaluate(signals, config_row.config)

    # Explainability invariant (spec §14): never persist a non-low assessment
    # without findings; the score must equal the clamped sum of its findings.
    if result.tier != "low":
        assert result.findings, "non-low tier must carry at least one finding"
    assert result.overall_score == min(100.0, sum(f.weight_contribution for f in result.findings))

    current, current_signature = _current_assessment_and_signature(session, tenant_id, student_id)
    if current_signature == _result_signature(result):
        return "unchanged"

    computed_at = date.today()
    minor_status = compute_subject_minor_status(signals.dob, computed_at)
    previous_tier = current.tier if current is not None else None

    if current is not None:
        current.is_current = False

    new_assessment = RiskAssessment(
        tenant_id=tenant_id,
        student_id=student_id,
        is_current=True,
        model_type=result.model_type,
        model_version=result.model_version,
        config_version=config_row.version,
        overall_score=result.overall_score,
        tier=result.tier,
        subject_minor_status=minor_status,
        signals_snapshot=signals_to_jsonable(signals),
        triggered_by=triggered_by,
        triggered_by_import_batch_id=import_batch_id,
    )
    session.add(new_assessment)
    session.flush()

    for finding in result.findings:
        session.add(
            RiskFinding(
                tenant_id=tenant_id,
                assessment_id=new_assessment.id,
                risk_type=finding.risk_type.value,
                code=finding.code,
                severity=finding.severity.value,
                weight_contribution=finding.weight_contribution,
                message=finding.message,
                evidence=finding.evidence,
            )
        )
    session.flush()

    generate_alert_if_material(session, tenant_id, student_id, new_assessment, previous_tier=previous_tier)
    return "changed"


def recompute_for_students(
    session: Session,
    tenant_id: UUID,
    student_ids: list[UUID],
    *,
    triggered_by: str,
    import_batch_id: UUID | None = None,
) -> RecomputeSummary:
    summary = RecomputeSummary()
    unique_ids = list(dict.fromkeys(student_ids))  # de-dup, preserve order -> deterministic
    if not unique_ids:
        return summary

    set_tenant_context(session, tenant_id)
    config_row = get_or_seed_config(session, tenant_id)
    signals_map = _bulk_compute_signals(session, tenant_id, unique_ids, config_row.config)

    for student_id in unique_ids:
        signals = signals_map.get(student_id)
        if signals is None:
            summary.skipped += 1
            continue
        try:
            with session.begin_nested():
                outcome = _persist_one(
                    session, tenant_id, student_id, signals, config_row, triggered_by, import_batch_id
                )
            summary.evaluated += 1
            if outcome == "changed":
                summary.changed += 1
            else:
                summary.unchanged += 1
        except Exception as exc:  # noqa: BLE001 - isolate one student's failure (spec §10.2 step 5)
            logger.exception("Risk recompute failed for student_id=%s", student_id)
            summary.errors.append({"student_id": str(student_id), "error": str(exc)})

    return summary


def recompute_for_tenant(session: Session, tenant_id: UUID, *, triggered_by: str) -> RecomputeSummary:
    set_tenant_context(session, tenant_id)
    student_ids = session.execute(
        select(Student.id).where(Student.tenant_id == tenant_id, Student.is_deleted.is_(False))
    ).scalars().all()
    return recompute_for_students(session, tenant_id, list(student_ids), triggered_by=triggered_by)


def recompute_for_import_batch(session: Session, tenant_id: UUID, import_batch_id: UUID) -> RecomputeSummary:
    """Derives affected student_ids from the batch's staging_records.
    resolved_entity_id for risk-relevant entity types (spec §10.1)."""
    set_tenant_context(session, tenant_id)
    batch = session.get(ImportBatch, import_batch_id)
    if batch is None or batch.entity_type not in _RISK_RELEVANT_ENTITY_TYPES:
        return RecomputeSummary()

    resolved_ids = session.execute(
        select(StagingRecord.resolved_entity_id).where(
            StagingRecord.tenant_id == tenant_id,
            StagingRecord.import_batch_id == import_batch_id,
            StagingRecord.resolved_entity_id.is_not(None),
        )
    ).scalars().all()

    if batch.entity_type == "student":
        student_ids = list(resolved_ids)
    else:
        student_ids = _student_ids_for_entity_rows(session, tenant_id, batch.entity_type, list(resolved_ids))

    return recompute_for_students(session, tenant_id, student_ids, triggered_by="import", import_batch_id=import_batch_id)


def _student_ids_for_entity_rows(
    session: Session, tenant_id: UUID, entity_type: str, resolved_ids: list[UUID]
) -> list[UUID]:
    if not resolved_ids:
        return []
    model = _ENTITY_MODEL_BY_TYPE[entity_type]
    rows = session.execute(
        select(model.student_id).where(
            model.tenant_id == tenant_id, model.id.in_(resolved_ids), model.student_id.is_not(None)
        )
    ).scalars().all()
    return list(dict.fromkeys(rows))
