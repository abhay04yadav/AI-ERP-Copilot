"""Acceptance test §15.2: each rule in isolation fires exactly when its
condition holds and not otherwise; the attendance-below-threshold confidence
guard is tested explicitly."""

from uuid import uuid4

from app.services.risk.config import DEFAULT_RISK_CONFIG
from app.services.risk.rules.academic_rules import AcademicDecline, AcademicFailingInternals
from app.services.risk.rules.attendance_rules import AttendanceBelowThreshold, AttendanceDeclining
from app.services.risk.rules.fee_rules import FeeOverdue
from app.services.risk.signals.base import StudentSignals

CONFIG = DEFAULT_RISK_CONFIG


def _signals(**overrides) -> StudentSignals:
    base = dict(
        student_id=uuid4(),
        dob=None,
        overall_attendance_pct=None,
        overall_sessions=0,
        attendance_by_course=(),
        attendance_recent_pct=None,
        attendance_prior_pct=None,
        latest_internal_pct_by_course=(),
        failing_internal_count=0,
        academic_latest_pct=None,
        academic_baseline_pct=None,
        max_fee_overdue_days=0,
    )
    base.update(overrides)
    return StudentSignals(**base)


def test_attendance_below_threshold_fires_when_below_with_enough_sessions():
    signals = _signals(overall_attendance_pct=60.0, overall_sessions=20)
    finding = AttendanceBelowThreshold().evaluate(signals, CONFIG)
    assert finding is not None
    assert finding.code == "ATTENDANCE_BELOW_THRESHOLD"
    assert finding.weight_contribution == CONFIG["weights"]["ATTENDANCE_BELOW_THRESHOLD"]
    assert "60.0%" in finding.message and "75%" in finding.message


def test_attendance_below_threshold_does_not_fire_above_threshold():
    signals = _signals(overall_attendance_pct=80.0, overall_sessions=20)
    assert AttendanceBelowThreshold().evaluate(signals, CONFIG) is None


def test_attendance_below_threshold_confidence_guard_blocks_tiny_sample():
    """Acceptance test §15.2: must NOT fire below attendance_min_sessions even
    though the pct itself is below threshold."""
    signals = _signals(overall_attendance_pct=50.0, overall_sessions=5)
    assert AttendanceBelowThreshold().evaluate(signals, CONFIG) is None


def test_attendance_below_threshold_none_pct_does_not_fire():
    signals = _signals(overall_attendance_pct=None, overall_sessions=20)
    assert AttendanceBelowThreshold().evaluate(signals, CONFIG) is None


def test_attendance_declining_fires_on_sufficient_drop():
    signals = _signals(attendance_recent_pct=60.0, attendance_prior_pct=80.0)
    finding = AttendanceDeclining().evaluate(signals, CONFIG)
    assert finding is not None
    assert finding.code == "ATTENDANCE_DECLINING"
    assert finding.evidence["drop"] == 20.0


def test_attendance_declining_does_not_fire_on_small_drop():
    signals = _signals(attendance_recent_pct=72.0, attendance_prior_pct=80.0)
    assert AttendanceDeclining().evaluate(signals, CONFIG) is None


def test_attendance_declining_does_not_fire_when_either_window_missing():
    assert AttendanceDeclining().evaluate(_signals(attendance_recent_pct=60.0), CONFIG) is None
    assert AttendanceDeclining().evaluate(_signals(attendance_prior_pct=80.0), CONFIG) is None


def test_academic_failing_internals_fires_on_at_least_one():
    signals = _signals(failing_internal_count=1)
    finding = AcademicFailingInternals().evaluate(signals, CONFIG)
    assert finding is not None
    assert finding.code == "ACADEMIC_FAILING_INTERNALS"
    assert "1 internal(s) below 40%" == finding.message


def test_academic_failing_internals_does_not_fire_on_zero():
    assert AcademicFailingInternals().evaluate(_signals(failing_internal_count=0), CONFIG) is None


def test_academic_decline_fires_on_sufficient_drop():
    signals = _signals(academic_latest_pct=50.0, academic_baseline_pct=70.0)
    finding = AcademicDecline().evaluate(signals, CONFIG)
    assert finding is not None
    assert finding.code == "ACADEMIC_DECLINE"
    assert finding.evidence["drop"] == 20.0


def test_academic_decline_does_not_fire_on_small_drop():
    signals = _signals(academic_latest_pct=65.0, academic_baseline_pct=70.0)
    assert AcademicDecline().evaluate(signals, CONFIG) is None


def test_academic_decline_does_not_fire_when_either_missing():
    assert AcademicDecline().evaluate(_signals(academic_latest_pct=50.0), CONFIG) is None
    assert AcademicDecline().evaluate(_signals(academic_baseline_pct=70.0), CONFIG) is None


def test_fee_overdue_fires_at_or_above_threshold():
    signals = _signals(max_fee_overdue_days=30)
    finding = FeeOverdue().evaluate(signals, CONFIG)
    assert finding is not None
    assert finding.code == "FEE_OVERDUE"
    assert finding.message == "Fees overdue 30 days"


def test_fee_overdue_does_not_fire_below_threshold():
    assert FeeOverdue().evaluate(_signals(max_fee_overdue_days=29), CONFIG) is None


def test_fee_overdue_zero_days_does_not_fire():
    assert FeeOverdue().evaluate(_signals(max_fee_overdue_days=0), CONFIG) is None
