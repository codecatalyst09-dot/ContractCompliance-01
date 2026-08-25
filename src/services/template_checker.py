import re
from typing import List, Optional, Tuple

from src.models.schemas import ClauseFinding, ComplianceStatus, ExtractedDocument, Severity
from src.services.policy_service import Policy


def _contains_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def _severity_from_policy(policy: Policy) -> Severity:
    sev = (policy.severity or "").upper()
    if sev in Severity.__members__:
        return Severity[sev]
    return Severity.HIGH


def _find_template_policy(policies: List[Policy]) -> Optional[Policy]:
    for p in policies:
        category = (p.category or "").lower()
        name = (p.name or "").lower()
        requirement = (p.requirement or "").lower()
        if "template" in category or "template" in name or "mandatory sections" in requirement:
            return p
    return None


def evaluate_template_policy(doc: ExtractedDocument, policies: List[Policy]) -> Optional[ClauseFinding]:
    """
    Deterministically validates core contract-template sections.
    Returns a ClauseFinding for the template policy if available.
    """
    template_policy = _find_template_policy(policies)
    if not template_policy:
        return None

    text = (doc.text or "").lower()
    if not text.strip():
        return ClauseFinding(
            policy_id=template_policy.policy_id,
            policy_name=template_policy.name,
            clause_reference=None,
            status=ComplianceStatus.NOT_FOUND,
            finding="Template validation could not run because extracted contract text is empty.",
            severity=_severity_from_policy(template_policy),
            evidence=None,
        )

    checks: List[Tuple[str, List[str]]] = [
        ("Parties / Recitals / Effective Date", [r"\bbetween\b", r"\beffective\s+date\b", r"\brecitals?\b", r"\bwitnesseth\b"]),
        ("Scope / Deliverables", [r"\bscope\b", r"\bservices?\b", r"\bdeliverables?\b"]),
        ("Payment / Fees", [r"\bpayment\b", r"\bfees?\b", r"\binvoice\b", r"\bnet\s*\d+\b"]),
        ("Term / Termination", [r"\bterm\b", r"\btermination\b", r"\bterminate\b"]),
        ("Confidentiality", [r"\bconfidential(?:ity)?\b", r"\bnon[-\s]?disclosure\b", r"\bnda\b"]),
        ("Limitation of Liability", [r"\blimitation\s+of\s+liability\b", r"\bliability\b", r"\bconsequential\s+damages?\b"]),
        ("Governing Law", [r"\bgoverning\s+law\b", r"\bjurisdiction\b"]),
        ("Authorized Signatures Block", [r"\bsignature\b", r"\bsigned\b", r"\bauthorized\s+signatory\b", r"\bin\s+witness\s+whereof\b"]),
    ]

    missing_sections: List[str] = []
    matched_sections: List[str] = []
    for section_name, patterns in checks:
        if _contains_any(text, patterns):
            matched_sections.append(section_name)
        else:
            missing_sections.append(section_name)

    found_count = len(matched_sections)
    total = len(checks)

    if found_count == total:
        status = ComplianceStatus.COMPLIANT
        finding = "All mandatory template sections were detected."
    elif found_count >= 5:
        status = ComplianceStatus.PARTIAL
        finding = f"Template is partially complete. Missing sections: {', '.join(missing_sections)}."
    elif found_count >= 1:
        status = ComplianceStatus.NON_COMPLIANT
        finding = f"Template is materially incomplete. Missing sections: {', '.join(missing_sections)}."
    else:
        status = ComplianceStatus.NOT_FOUND
        finding = "No mandatory template sections were confidently detected in extracted text."

    evidence = (
        f"Detected {found_count}/{total} required sections. "
        f"Found: {', '.join(matched_sections) if matched_sections else 'None'}."
    )

    return ClauseFinding(
        policy_id=template_policy.policy_id,
        policy_name=template_policy.name,
        clause_reference="Template Structure",
        status=status,
        finding=finding,
        severity=_severity_from_policy(template_policy),
        evidence=evidence,
    )

