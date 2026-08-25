import json
import re
from typing import List, Optional

from agent_framework import Agent
from src.agents.client_factory import get_chat_client
from src.models.schemas import (
    ClauseFinding,
    ComplianceStatus,
    ExtractedDocument,
    ObligationResult,
    Severity,
)
from src.services.risky_terms_checker import detect_risky_terms_heuristic

RISKY_TERMS_SYSTEM_INSTRUCTION = """You are a contract risk analyst specializing in commercially dangerous terms.

Detect ONLY risky or one-sided terms that actually appear in the contract text. Do not invent clauses.

Common risk categories to look for:
- Unlimited or uncapped liability
- Automatic renewal / evergreen terms
- Unilateral amendment or termination rights
- One-sided indemnity or hold-harmless
- Payment terms longer than Net 60
- Broad as-is / warranty disclaimers
- Non-refundable fees with no service-credit remedy
- Restrictive assignment blocking M&A or subcontracting
- Missing termination for convenience
- Customer-unfriendly governing law / exclusive venue
- Audit rights that are missing or overly invasive
- IP assignment that strips the customer of residual rights

For each detected risk return:
- policy_id: stable id like "RISK-UNLIMITED-LIABILITY"
- policy_name: short risk title
- clause_reference: section name if present, else null
- status: always "NON_COMPLIANT" for a detected risk, or "PARTIAL" if mitigated but still concerning
- finding: why this term is risky
- severity: CRITICAL, HIGH, MEDIUM, or LOW
- evidence: verbatim snippet from the contract

If no risky terms are found, return {"findings": []}.

Return ONLY valid JSON:
{"findings": [ ... ]}
"""


from src.agents.json_utils import robust_parse_json


class RiskyTermsAgent:
    def __init__(self):
        client = get_chat_client()
        self.agent = Agent(
            client=client,
            name="RiskyTermsAgent",
            instructions=RISKY_TERMS_SYSTEM_INSTRUCTION,
        )

    async def detect_risky_terms(
        self,
        doc: ExtractedDocument,
        obligations: Optional[ObligationResult] = None,
    ) -> List[ClauseFinding]:
        heuristic_findings = detect_risky_terms_heuristic(doc)
        obl_summary = ""
        if obligations and obligations.obligations:
            obl_summary = json.dumps(
                [
                    {
                        "obligation_id": o.obligation_id,
                        "description": o.description,
                        "penalty": o.penalty,
                        "clause_reference": o.clause_reference,
                    }
                    for o in obligations.obligations
                ],
                indent=2,
            )

        prompt = f"""Contract Document: {doc.file_name}

Contract Full Text:
{doc.text}

Extracted Obligations (may be empty):
{obl_summary or "None"}
"""
        try:
            from src.agents.retry_utils import execute_with_retry
            response = await execute_with_retry(self.agent.run, prompt)
            response_text = getattr(response, "text", str(response)).strip()
            data = robust_parse_json(response_text, expected_keys=["findings"])
            llm_findings = self._parse_findings(data.get("findings", []))
        except Exception:
            llm_findings = []

        return self._merge_findings(heuristic_findings, llm_findings)

    @staticmethod
    def _parse_findings(raw_findings: list) -> List[ClauseFinding]:
        parsed: List[ClauseFinding] = []
        for item in raw_findings:
            status_str = str(item.get("status", "NON_COMPLIANT")).strip().upper()
            try:
                status_enum = ComplianceStatus(status_str)
            except ValueError:
                status_enum = ComplianceStatus.NON_COMPLIANT
            if status_enum == ComplianceStatus.COMPLIANT:
                continue

            severity_str = str(item.get("severity", "HIGH")).strip().upper()
            try:
                severity_enum = Severity(severity_str)
            except ValueError:
                severity_enum = Severity.HIGH

            parsed.append(
                ClauseFinding(
                    policy_id=str(item.get("policy_id") or "RISK-UNKNOWN").strip().upper(),
                    policy_name=str(item.get("policy_name") or "Detected Risky Term"),
                    clause_reference=item.get("clause_reference"),
                    status=status_enum,
                    finding=str(item.get("finding", "Risky contract term detected.")),
                    severity=severity_enum,
                    evidence=item.get("evidence"),
                )
            )
        return parsed

    @staticmethod
    def _merge_findings(heuristic: List[ClauseFinding], llm: List[ClauseFinding]) -> List[ClauseFinding]:
        merged: dict[str, ClauseFinding] = {}
        for finding in heuristic + llm:
            key = finding.policy_id.upper()
            existing = merged.get(key)
            if not existing:
                merged[key] = finding
                continue
            severity_rank = {
                Severity.LOW: 1,
                Severity.MEDIUM: 2,
                Severity.HIGH: 3,
                Severity.CRITICAL: 4,
            }
            if severity_rank.get(finding.severity, 0) > severity_rank.get(existing.severity, 0):
                merged[key] = finding
            elif not existing.evidence and finding.evidence:
                merged[key] = finding
        return list(merged.values())
