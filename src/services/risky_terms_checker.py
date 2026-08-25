import re
from typing import List, Tuple

from src.models.schemas import ClauseFinding, ComplianceStatus, ExtractedDocument, Severity


def _match(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def detect_risky_terms_heuristic(doc: ExtractedDocument) -> List[ClauseFinding]:
    """
    Deterministic red-flag scan for common high-risk contract terms.
    Only emits findings when a risky pattern is actually present.
    """
    text = doc.text or ""
    if not text.strip():
        return []

    rules: List[Tuple[str, str, str, str, Severity]] = [
        (
            "RISK-UNLIMITED-LIABILITY",
            "Unlimited Liability",
            r"\bunlimited\s+liabilit|\bno\s+cap\s+on\s+liabilit|\bwithout\s+limitation\s+of\s+liabilit",
            "Contract language indicates uncapped or unlimited liability exposure.",
            Severity.CRITICAL,
        ),
        (
            "RISK-AUTO-RENEWAL",
            "Automatic Renewal / Evergreen Term",
            r"\bauto(?:matic(?:ally)?)?\s+renew|\bevergreen\b|\bshall\s+renew\s+automatically\b",
            "Automatic renewal / evergreen language can lock the party into successive terms.",
            Severity.HIGH,
        ),
        (
            "RISK-UNILATERAL-AMENDMENT",
            "Unilateral Amendment Right",
            r"\b(?:may|shall)\s+(?:unilaterally\s+)?(?:amend|modify|change)\s+(?:this\s+)?(?:agreement|contract)\s+without\b|\bin\s+its\s+sole\s+discretion\s+(?:amend|modify)",
            "One party may amend the contract without mutual consent.",
            Severity.HIGH,
        ),
        (
            "RISK-ONE-SIDED-INDEMNITY",
            "One-Sided Indemnity",
            r"\b(?:customer|client|buyer)\s+shall\s+indemnify\b|\bindemnify.{0,80}\b(?:provider|vendor|supplier)\b.{0,40}\bhold\s+harmless\b",
            "Indemnity appears one-sided and may over-allocate risk to one party.",
            Severity.HIGH,
        ),
        (
            "RISK-EXTENDED-PAYMENT",
            "Extended Payment Terms",
            r"\bnet\s*(?:90|120|180)\b|\bpayment.{0,40}(?:90|120|180)\s+days\b",
            "Payment terms appear longer than typical Net 60 commercial policy limits.",
            Severity.HIGH,
        ),
        (
            "RISK-NO-CONSEQUENTIAL-EXCLUSION",
            "Missing / Weak Indirect Damages Exclusion",
            r"\b(?:including|including without limitation)\s+consequential\s+damages\b",
            "Language may keep consequential/indirect damages in scope rather than excluding them.",
            Severity.MEDIUM,
        ),
        (
            "RISK-NON-REFUNDABLE",
            "Non-Refundable Fees",
            r"\bnon[-\s]?refundable\b|\bno\s+refunds?\b",
            "Non-refundable fee language reduces commercial flexibility on termination or non-performance.",
            Severity.MEDIUM,
        ),
        (
            "RISK-AS-IS-WARRANTY",
            "As-Is / Disclaimer of Warranties",
            r"\bas[-\s]?is\b.{0,40}\bwarrant|\bno\s+warrant(?:y|ies)\b|\bdisclaim(?:s|er).{0,40}warrant",
            "Broad warranty disclaimer / as-is delivery increases operational and quality risk.",
            Severity.MEDIUM,
        ),
        (
            "RISK-ASSIGNMENT-LOCK",
            "Restrictive Assignment",
            r"\bmay\s+not\s+assign\b|\bshall\s+not\s+assign\b|\bno\s+assignment\s+without\b",
            "Assignment is heavily restricted, which can block restructuring, outsourcing, or M&A flexibility.",
            Severity.LOW,
        ),
    ]

    findings: List[ClauseFinding] = []
    for risk_id, name, pattern, explanation, severity in rules:
        if _match(text, pattern):
            snippet = _evidence_snippet(text, pattern)
            findings.append(
                ClauseFinding(
                    policy_id=risk_id,
                    policy_name=name,
                    clause_reference="Risky Term Scan",
                    status=ComplianceStatus.NON_COMPLIANT,
                    finding=explanation,
                    severity=severity,
                    evidence=snippet,
                )
            )
    return findings


def _evidence_snippet(text: str, pattern: str, window: int = 180) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return "Risky term pattern matched in contract text."
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    snippet = text[start:end].strip().replace("\n", " ")
    return snippet[:400]
