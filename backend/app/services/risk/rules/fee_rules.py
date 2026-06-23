"""Fee rule, rule set v1 (spec §6.3). Pure: no I/O, no DB, no clock."""

from app.services.risk.rules.base import RiskFinding, RiskType, Severity
from app.services.risk.signals.base import StudentSignals


class FeeOverdue:
    code = "FEE_OVERDUE"

    def evaluate(self, signals: StudentSignals, config: dict) -> RiskFinding | None:
        threshold = config["fee_overdue_days"]
        days = signals.max_fee_overdue_days
        if days < threshold:
            return None
        return RiskFinding(
            risk_type=RiskType.FEE,
            code=self.code,
            severity=Severity.LOW,
            weight_contribution=config["weights"][self.code],
            message=f"Fees overdue {days} days",
            evidence={"overdue_days": days, "threshold": threshold},
        )
