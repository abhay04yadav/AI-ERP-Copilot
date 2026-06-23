"""Academic rules, rule set v1 (spec §6.3). Pure: no I/O, no DB, no clock."""

from app.services.risk.rules.base import RiskFinding, RiskType, Severity
from app.services.risk.signals.base import StudentSignals


class AcademicFailingInternals:
    code = "ACADEMIC_FAILING_INTERNALS"

    def evaluate(self, signals: StudentSignals, config: dict) -> RiskFinding | None:
        fail_pct = config["academic_fail_pct"]
        n = signals.failing_internal_count
        if n < 1:
            return None
        return RiskFinding(
            risk_type=RiskType.ACADEMIC,
            code=self.code,
            severity=Severity.HIGH,
            weight_contribution=config["weights"][self.code],
            message=f"{n} internal(s) below {fail_pct}%",
            evidence={"failing_count": n, "threshold": fail_pct},
        )


class AcademicDecline:
    code = "ACADEMIC_DECLINE"

    def evaluate(self, signals: StudentSignals, config: dict) -> RiskFinding | None:
        decline_points = config["academic_decline_points"]
        latest = signals.academic_latest_pct
        baseline = signals.academic_baseline_pct
        if latest is None or baseline is None:
            return None
        drop = round(baseline - latest, 2)
        if drop < decline_points:
            return None
        return RiskFinding(
            risk_type=RiskType.ACADEMIC,
            code=self.code,
            severity=Severity.MEDIUM,
            weight_contribution=config["weights"][self.code],
            message=f"Latest internal {latest}% vs baseline {baseline}%",
            evidence={"latest_pct": latest, "baseline_pct": baseline, "drop": drop, "threshold": decline_points},
        )
