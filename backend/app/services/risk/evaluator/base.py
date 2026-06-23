"""The future-proof seam (spec §8). The engine, storage, and API depend only
on RiskEvaluator + AssessmentResult, so a future MLRiskEvaluator (different
model_type/model_version, same output shape) is a drop-in with zero changes
to callers. Do not build the ML evaluator now (spec §16)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.risk.rules.base import RiskFinding
from app.services.risk.signals.base import StudentSignals


@dataclass(frozen=True)
class AssessmentResult:
    overall_score: float
    tier: str
    findings: list[RiskFinding]
    model_type: str  # 'rules'
    model_version: str  # 'rules-v1'


class RiskEvaluator(ABC):
    @abstractmethod
    def evaluate(self, signals: StudentSignals, config: dict) -> AssessmentResult: ...
