"""The rule set v1, in evaluation order (spec §6.3 table)."""

from app.services.risk.rules.academic_rules import AcademicDecline, AcademicFailingInternals
from app.services.risk.rules.attendance_rules import AttendanceBelowThreshold, AttendanceDeclining
from app.services.risk.rules.fee_rules import FeeOverdue

ACTIVE_RULES = (
    AttendanceBelowThreshold(),
    AttendanceDeclining(),
    AcademicFailingInternals(),
    AcademicDecline(),
    FeeOverdue(),
)
