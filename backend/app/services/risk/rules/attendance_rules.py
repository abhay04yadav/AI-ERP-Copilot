"""Attendance rules, rule set v1 (spec §6.3). Pure: no I/O, no DB, no clock."""

from app.services.risk.rules.base import RiskFinding, RiskType, Severity
from app.services.risk.signals.base import StudentSignals


class AttendanceBelowThreshold:
    code = "ATTENDANCE_BELOW_THRESHOLD"

    def evaluate(self, signals: StudentSignals, config: dict) -> RiskFinding | None:
        threshold = config["attendance_threshold_pct"]
        min_sessions = config["attendance_min_sessions"]
        pct = signals.overall_attendance_pct
        # Confidence guard (spec §6.3 note): never fire on a tiny sample —
        # prevents false flags early in a term. Part of correctness, not an
        # optimization.
        if pct is None or signals.overall_sessions < min_sessions:
            return None
        if pct >= threshold:
            return None
        return RiskFinding(
            risk_type=RiskType.ATTENDANCE,
            code=self.code,
            severity=Severity.HIGH,
            weight_contribution=config["weights"][self.code],
            message=f"Attendance {pct}% (below {threshold}%)",
            evidence={
                "scope": "overall",
                "value": pct,
                "threshold": threshold,
                "sessions": signals.overall_sessions,
            },
        )


class AttendanceDeclining:
    code = "ATTENDANCE_DECLINING"

    def evaluate(self, signals: StudentSignals, config: dict) -> RiskFinding | None:
        decline_points = config["attendance_decline_points"]
        recent = signals.attendance_recent_pct
        prior = signals.attendance_prior_pct
        if recent is None or prior is None:
            return None
        drop = round(prior - recent, 2)
        if drop < decline_points:
            return None
        return RiskFinding(
            risk_type=RiskType.ATTENDANCE,
            code=self.code,
            severity=Severity.MEDIUM,
            weight_contribution=config["weights"][self.code],
            message=f"Attendance fell {drop} pts ({prior}%→{recent}%)",
            evidence={
                "scope": "trend",
                "prior_pct": prior,
                "recent_pct": recent,
                "drop": drop,
                "threshold": decline_points,
            },
        )
