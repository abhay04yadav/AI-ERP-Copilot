"""Aggregate findings -> score; score -> tier (spec §7). Deterministic and
explainable: the score always reconciles exactly with the sum of findings."""

from app.services.risk.rules.base import RiskFinding


def score_findings(findings: list[RiskFinding]) -> float:
    return min(100.0, sum(f.weight_contribution for f in findings))


def tier_for_score(score: float, config: dict) -> str:
    cutoffs = config["tier_cutoffs"]
    if score >= cutoffs["high"]:
        return "high"
    if score >= cutoffs["watch"]:
        return "watch"
    return "low"
