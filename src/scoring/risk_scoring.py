from typing import List, Dict, Any, Optional
from src.models.schemas import ClauseFinding, ComplianceStatus, Severity, RiskScore

# Configurable Risk Weights & Status Multipliers
DEFAULT_SEVERITY_WEIGHTS: Dict[Severity, int] = {
    Severity.CRITICAL: 40,
    Severity.HIGH: 25,
    Severity.MEDIUM: 10,
    Severity.LOW: 5
}

DEFAULT_STATUS_MULTIPLIERS: Dict[ComplianceStatus, float] = {
    ComplianceStatus.NON_COMPLIANT: 1.0,
    ComplianceStatus.NOT_FOUND: 1.0,
    ComplianceStatus.PARTIAL: 0.5,
    ComplianceStatus.COMPLIANT: 0.0
}


def determine_risk_level(score: int) -> Severity:
    if score >= 75:
        return Severity.CRITICAL
    elif score >= 50:
        return Severity.HIGH
    elif score >= 20:
        return Severity.MEDIUM
    else:
        return Severity.LOW


def calculate_risk_score(
    findings: List[ClauseFinding],
    weights: Dict[Severity, int] = DEFAULT_SEVERITY_WEIGHTS,
    multipliers: Dict[ComplianceStatus, float] = DEFAULT_STATUS_MULTIPLIERS,
    benchmark_policy_count: Optional[int] = None,
    gamma: float = 0.75
) -> RiskScore:
    """
    Deterministically calculates numerical contract risk score (0 to 100) and risk level.
    
    Model Design:
    - Instead of naive linear summation capping early at 100, computes proportional incurred risk
      against total evaluable potential severity.
    - Uses calibrated concave scaling (gamma=0.75) to provide meaningful sensitivity for early critical
      failures while preserving clear monotonic differentiation across the entire 0-100 spectrum.
    - 3 critical failures do not prematurely hit 100, distinguishing high risk from total catastrophic failure.
    """
    if not findings:
        return RiskScore(
            score=0,
            risk_level=Severity.LOW,
            breakdown={
                "incurred_penalty": 0.0,
                "max_possible_penalty": 0.0,
                "risk_ratio": 0.0,
                "counts": {"compliant": 0, "non_compliant": 0, "partial": 0, "not_found": 0},
                "finding_penalties": []
            }
        )

    incurred_penalty = 0.0
    total_potential_weight = 0.0
    finding_scores: List[Dict[str, Any]] = []

    non_compliant_count = 0
    partial_count = 0
    not_found_count = 0
    compliant_count = 0

    for f in findings:
        weight = weights.get(f.severity, 10)
        multiplier = multipliers.get(f.status, 0.0)
        penalty = weight * multiplier

        incurred_penalty += penalty
        total_potential_weight += weight

        if f.status == ComplianceStatus.NON_COMPLIANT:
            non_compliant_count += 1
        elif f.status == ComplianceStatus.PARTIAL:
            partial_count += 1
        elif f.status == ComplianceStatus.NOT_FOUND:
            not_found_count += 1
        elif f.status == ComplianceStatus.COMPLIANT:
            compliant_count += 1

        finding_scores.append({
            "policy_id": f.policy_id,
            "policy_name": f.policy_name,
            "status": f.status.value,
            "severity": f.severity.value,
            "weight": weight,
            "multiplier": multiplier,
            "penalty": penalty
        })

    # If benchmark policy count is given and exceeds current findings, adjust potential capacity
    if benchmark_policy_count and benchmark_policy_count > len(findings):
        avg_weight = total_potential_weight / len(findings) if findings else 20.0
        total_potential_weight += (benchmark_policy_count - len(findings)) * avg_weight

    if total_potential_weight > 0:
        risk_ratio = incurred_penalty / total_potential_weight
        # Apply concave scaling: ensures single critical items carry noticeable risk,
        # but 3 critical failures out of 5 policies yields ~68 (High/Critical boundary) rather than saturating at 100.
        scaled_score = 100.0 * (risk_ratio ** gamma)
        final_numeric_score = max(0, min(100, int(round(scaled_score))))
    else:
        risk_ratio = 0.0
        final_numeric_score = 0

    risk_level = determine_risk_level(final_numeric_score)

    breakdown = {
        "incurred_penalty": incurred_penalty,
        "max_possible_penalty": total_potential_weight,
        "risk_ratio": round(risk_ratio, 4),
        "scaling_gamma": gamma,
        "raw_score": round(scaled_score, 2) if total_potential_weight > 0 else 0.0,
        "final_score": final_numeric_score,
        "counts": {
            "compliant": compliant_count,
            "non_compliant": non_compliant_count,
            "partial": partial_count,
            "not_found": not_found_count
        },
        "finding_penalties": finding_scores
    }

    return RiskScore(
        score=final_numeric_score,
        risk_level=risk_level,
        breakdown=breakdown
    )
