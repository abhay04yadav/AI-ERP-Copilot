"""Acceptance test §15.3: a known finding set yields the exact score and
tier; findings==[] => score==0 and tier=='low' (the direction §15.3's
acceptance text actually states and that always holds for any config, since
score_findings([]) == 0 and a score of 0 is below any positive watch
cutoff).

Note (CHANGELOG.md): §7's prose also states the reverse implication
(tier=='low' => findings==[]) as a general invariant, but the named default
weights/cutoffs (§6.1) don't actually guarantee it: a lone FEE_OVERDUE
finding (weight 15) scores 15, which is below the default watch cutoff of
25, so it tiers 'low' while a finding is present. Scoring is specified as
exactly "clamped sum of weights" and tiering as exactly "score vs
threshold" with no other logic, so this is a property of the configured
numbers, not a defect in scoring.py/the rule evaluation — documented rather
than special-cased.
"""

from app.services.risk.rules.base import RiskFinding, RiskType, Severity
from app.services.risk.scoring import score_findings, tier_for_score

CONFIG = {
    "weights": {
        "ATTENDANCE_BELOW_THRESHOLD": 40,
        "ATTENDANCE_DECLINING": 20,
        "ACADEMIC_FAILING_INTERNALS": 35,
        "ACADEMIC_DECLINE": 20,
        "FEE_OVERDUE": 15,
    },
    "tier_cutoffs": {"watch": 25, "high": 50},
}


def _finding(code: str, weight: float) -> RiskFinding:
    return RiskFinding(
        risk_type=RiskType.ATTENDANCE,
        code=code,
        severity=Severity.HIGH,
        weight_contribution=weight,
        message="x",
        evidence={},
    )


def test_empty_findings_score_zero_and_tier_low():
    assert score_findings([]) == 0.0
    assert tier_for_score(score_findings([]), CONFIG) == "low"


def test_known_finding_set_yields_exact_score_and_tier():
    findings = [_finding("ATTENDANCE_BELOW_THRESHOLD", 40), _finding("ACADEMIC_FAILING_INTERNALS", 35)]
    score = score_findings(findings)
    assert score == 75.0
    assert tier_for_score(score, CONFIG) == "high"


def test_score_clamped_at_100():
    findings = [_finding("A", 60), _finding("B", 60)]
    assert score_findings(findings) == 100.0


def test_tier_boundaries_are_inclusive_of_cutoff():
    assert tier_for_score(25.0, CONFIG) == "watch"
    assert tier_for_score(24.99, CONFIG) == "low"
    assert tier_for_score(50.0, CONFIG) == "high"
    assert tier_for_score(49.99, CONFIG) == "watch"


def test_single_low_weight_finding_below_watch_cutoff_tiers_low():
    """Documents the §7/§6.1 edge case described in the module docstring."""
    findings = [_finding("FEE_OVERDUE", 15)]
    score = score_findings(findings)
    assert score == 15.0
    assert tier_for_score(score, CONFIG) == "low"


def test_default_config_is_valid():
    """Phase 2 hardening CHANGE 2c: the shipped default must always satisfy
    its own validation schema."""
    from app.schemas.risk import RiskConfigModel
    from app.services.risk.config import DEFAULT_RISK_CONFIG

    RiskConfigModel(**DEFAULT_RISK_CONFIG)
