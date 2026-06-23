"""RulesRiskEvaluator — Phase 2's deterministic rules implementation (spec §8).
Runs every rule in the registry, scores, tiers, and stamps model identity."""

from app.services.risk.evaluator.base import AssessmentResult, RiskEvaluator
from app.services.risk.rules.registry import ACTIVE_RULES
from app.services.risk.scoring import score_findings, tier_for_score
from app.services.risk.signals.base import StudentSignals

MODEL_TYPE = "rules"
MODEL_VERSION = "rules-v1"


class RulesRiskEvaluator(RiskEvaluator):
    def evaluate(self, signals: StudentSignals, config: dict) -> AssessmentResult:
        findings = []
        for rule in ACTIVE_RULES:
            finding = rule.evaluate(signals, config)
            if finding is not None:
                findings.append(finding)

        score = score_findings(findings)
        tier = tier_for_score(score, config)
        return AssessmentResult(
            overall_score=score, tier=tier, findings=findings, model_type=MODEL_TYPE, model_version=MODEL_VERSION
        )
