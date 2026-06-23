"""The engine's typed input (spec §5.1). Frozen, serializable — the JSON form
of StudentSignals is exactly what gets persisted as RiskAssessment.signals_snapshot
(explainability today, training data for a future MLRiskEvaluator)."""

from dataclasses import asdict, dataclass
from datetime import date
from uuid import UUID


@dataclass(frozen=True)
class CourseAttendance:
    course_code: str
    course_name: str
    present: int
    total: int
    pct: float | None  # None when total == 0


@dataclass(frozen=True)
class StudentSignals:
    student_id: UUID
    dob: date | None
    # attendance
    overall_attendance_pct: float | None
    overall_sessions: int
    attendance_by_course: tuple[CourseAttendance, ...]
    attendance_recent_pct: float | None  # last N sessions window
    attendance_prior_pct: float | None  # the window before that (for trend)
    # academic
    latest_internal_pct_by_course: tuple[tuple[str, float], ...]  # (course_code, pct)
    failing_internal_count: int
    academic_latest_pct: float | None  # most recent internal overall
    academic_baseline_pct: float | None  # mean of that student's prior internals
    # fees
    max_fee_overdue_days: int  # 0 if none overdue


def signals_to_jsonable(signals: StudentSignals) -> dict:
    """Converts to a plain dict of JSON-safe primitives (UUID/date -> str) for
    storage in the JSONB signals_snapshot column."""
    raw = asdict(signals)
    raw["student_id"] = str(signals.student_id)
    raw["dob"] = signals.dob.isoformat() if signals.dob else None
    return raw
