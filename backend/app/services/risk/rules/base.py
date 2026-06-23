"""Rule contract (spec §6.2). Rules are pure: no I/O, no DB, no clock. Each
returns None or exactly one RiskFinding; contribution is the configured
weight (fixed, not magnitude-scaled — magnitude lives in evidence)."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.services.risk.signals.base import StudentSignals


class RiskType(str, Enum):
    ATTENDANCE = "attendance"
    ACADEMIC = "academic"
    FEE = "fee"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RiskFinding:
    risk_type: RiskType
    code: str
    severity: Severity
    weight_contribution: float
    message: str
    evidence: dict


class Rule(Protocol):
    code: str

    def evaluate(self, signals: StudentSignals, config: dict) -> RiskFinding | None: ...
