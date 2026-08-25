import pytest
from src.scoring.risk_scoring import calculate_risk_score
from src.models.schemas import ClauseFinding, ComplianceStatus, Severity


def test_all_compliant():
    findings = [
        ClauseFinding(policy_id="POL-001", policy_name="Payment", status=ComplianceStatus.COMPLIANT, finding="OK", severity=Severity.HIGH),
        ClauseFinding(policy_id="POL-002", policy_name="Termination", status=ComplianceStatus.COMPLIANT, finding="OK", severity=Severity.HIGH),
    ]
    risk = calculate_risk_score(findings)
    assert risk.score == 0
    assert risk.risk_level == Severity.LOW


def test_single_high_non_compliant_and_medium_partial():
    # HIGH non-compliant = 25. MEDIUM partial = 5. CRITICAL compliant = 0. Total potential = 25+10+40 = 75.
    # Ratio = 30/75 = 0.40 -> (0.40^0.75)*100 = 50 -> HIGH risk.
    findings = [
        ClauseFinding(policy_id="POL-001", policy_name="Payment", status=ComplianceStatus.NON_COMPLIANT, finding="Net 90", severity=Severity.HIGH),
        ClauseFinding(policy_id="POL-005", policy_name="Liability", status=ComplianceStatus.PARTIAL, finding="Cap missing ratio", severity=Severity.MEDIUM),
        ClauseFinding(policy_id="POL-003", policy_name="Confidentiality", status=ComplianceStatus.COMPLIANT, finding="OK", severity=Severity.CRITICAL),
    ]
    risk = calculate_risk_score(findings)
    assert risk.score == 50
    assert risk.risk_level == Severity.HIGH
    assert risk.breakdown["risk_ratio"] == 0.4


def test_critical_failure_monotonic_progression_no_early_saturation():
    """
    Validates that 1, 2, 3, 4, and 5 critical failures out of 5 policies yield
    strictly monotonic increasing scores, and 3 critical failures does NOT saturate at 100.
    """
    def make_5_findings(non_compliant_critical_count: int):
        findings = []
        for i in range(5):
            pid = f"POL-00{i+1}"
            if i < non_compliant_critical_count:
                findings.append(
                    ClauseFinding(
                        policy_id=pid,
                        policy_name=f"Policy {i+1}",
                        status=ComplianceStatus.NON_COMPLIANT,
                        finding="Non compliant",
                        severity=Severity.CRITICAL
                    )
                )
            else:
                findings.append(
                    ClauseFinding(
                        policy_id=pid,
                        policy_name=f"Policy {i+1}",
                        status=ComplianceStatus.COMPLIANT,
                        finding="Compliant",
                        severity=Severity.CRITICAL
                    )
                )
        return findings

    score_1 = calculate_risk_score(make_5_findings(1)).score
    score_2 = calculate_risk_score(make_5_findings(2)).score
    score_3 = calculate_risk_score(make_5_findings(3)).score
    score_4 = calculate_risk_score(make_5_findings(4)).score
    score_5 = calculate_risk_score(make_5_findings(5)).score

    # Verify strict monotonic differentiation
    assert score_1 < score_2 < score_3 < score_4 < score_5
    # 3 critical failures must NOT saturate at 100
    assert score_3 < 100
    assert score_3 == 68  # 3/5 ratio = 0.60 -> (0.60^0.75)*100 = 68
    # 4 critical failures is 85
    assert score_4 == 85
    # 5 critical failures is 100
    assert score_5 == 100


def test_empty_findings():
    risk = calculate_risk_score([])
    assert risk.score == 0
    assert risk.risk_level == Severity.LOW
