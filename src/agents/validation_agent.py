import json
import re
from typing import List
from agent_framework import Agent
from src.agents.client_factory import get_chat_client
from src.models.schemas import (
    ExtractedDocument,
    ObligationResult,
    ClauseFinding,
    ComplianceResult,
    ComplianceStatus,
    Severity
)
from src.services.policy_service import Policy

VALIDATION_SYSTEM_INSTRUCTION = """You are a senior compliance auditor acting as a SECOND-LEVEL REVIEWER.
Your job is to validate initial policy matching findings against the original contract text to eliminate false positives and correct errors.

For each initial finding provided:
1. Check if the referenced clause and evidence exist in the actual contract text.
2. Verify if the assigned compliance status (COMPLIANT, NON_COMPLIANT, PARTIAL, NOT_FOUND) is accurate.
   - Example: Payment terms of Net 90 when policy allows max Net 60 is NON_COMPLIANT.
3. Verify if the severity (CRITICAL, HIGH, MEDIUM, LOW) is reasonable.
4. Correct any inaccurate status, finding description, or evidence snippet.
5. Do NOT invent evidence or clauses not present in the contract.

Return ONLY valid JSON formatted as:
{
  "validated_findings": [
    {
      "policy_id": "POL-001",
      "policy_name": "Payment Terms Policy",
      "clause_reference": "Section 1",
      "status": "NON_COMPLIANT",
      "finding": "Validated explanation...",
      "severity": "HIGH",
      "evidence": "Supported text snippet..."
    }
  ],
  "validation_summary": "Brief summary of validation review changes..."
}
"""

from src.agents.json_utils import robust_parse_json

class ComplianceValidationAgent:
    def __init__(self):
        client = get_chat_client()
        self.agent = Agent(
            client=client,
            name="ComplianceValidationAgent",
            instructions=VALIDATION_SYSTEM_INSTRUCTION
        )

    async def validate(
        self,
        doc: ExtractedDocument,
        obligations: ObligationResult,
        initial_findings: List[ClauseFinding],
        policies: List[Policy]
    ) -> ComplianceResult:
        
        findings_json = json.dumps([f.model_dump() for f in initial_findings], indent=2)

        prompt = f"""Contract Document: {doc.file_name}

Contract Full Text:
{doc.text}

Initial Policy Findings to Validate:
{findings_json}
"""
        from src.agents.retry_utils import execute_with_retry
        response = await execute_with_retry(self.agent.run, prompt)
        response_text = getattr(response, "text", str(response)).strip()

        validated_findings = self.parse_validation_response(response_text, initial_findings, policies)

        val_map = {f.policy_id.upper(): f for f in validated_findings}
        final_findings: List[ClauseFinding] = []
        for orig in initial_findings:
            if orig.policy_id.upper() in val_map:
                final_findings.append(val_map[orig.policy_id.upper()])
            else:
                final_findings.append(orig)

        # Apply deterministic ground-truth cross-checks against source contract text and policy criteria
        cross_checked_findings = self.apply_ground_truth_cross_checks(doc, final_findings, policies)
        overall_status = self.calculate_overall_status(cross_checked_findings)

        return ComplianceResult(
            overall_status=overall_status,
            findings=cross_checked_findings
        )

    @classmethod
    def apply_ground_truth_cross_checks(
        cls,
        doc: ExtractedDocument,
        findings: List[ClauseFinding],
        policies: List[Policy]
    ) -> List[ClauseFinding]:
        policy_map = {p.policy_id.upper(): p for p in policies}
        doc_text_norm = " ".join((doc.text or "").lower().split())
        verified_findings: List[ClauseFinding] = []

        for f in findings:
            policy = policy_map.get(f.policy_id.upper())
            status = f.status
            val_status = "VERIFIED"
            notes = f.validation_notes

            ev_str = (f.evidence or "").strip()
            ev_norm = " ".join(ev_str.lower().split())

            # 1. Verbatim quote ground-truth check
            if ev_norm and ev_norm not in ("not found in contract", "null", "none"):
                if ev_norm not in doc_text_norm and len(ev_norm) > 10:
                    # Check if at least significant portion is present
                    chunks = [ev_norm[i:i+30] for i in range(0, len(ev_norm), 30) if len(ev_norm[i:i+30]) >= 15]
                    if not any(ch in doc_text_norm for ch in chunks):
                        val_status = "UNVERIFIED_EVIDENCE"
                        notes = (notes + " | " if notes else "") + "Ground truth check: Evidence quote not found verbatim in contract."

            # 2. Objective / Numeric Contradiction Detection
            if policy:
                req_lower = policy.requirement.lower()
                ev_plus_finding = (ev_norm + " " + f.finding.lower())

                # Payment term contradiction check (e.g. Policy: max Net 60; Contract: Net 90, Net 120, etc.)
                if "net 60" in req_lower or "net 30" in req_lower or "payment" in policy.name.lower():
                    if any(term in ev_plus_finding or term in doc_text_norm for term in ["net 90", "net 120", "net 75", "net 180"]):
                        if status == ComplianceStatus.COMPLIANT:
                            status = ComplianceStatus.NON_COMPLIANT
                            val_status = "CORRECTED"
                            notes = (notes + " | " if notes else "") + "Ground truth correction: Contract specifies payment term exceeding policy limit (Net > 60), corrected from COMPLIANT to NON_COMPLIANT."

                # Security Breach Notification contradiction check (e.g. Policy: <= 24 hours; Contract: 48 hours, 72 hours, 5 days)
                if "24 hours" in req_lower or "breach" in policy.name.lower() or "security" in policy.name.lower():
                    if any(term in ev_plus_finding or term in doc_text_norm for term in ["48 hours", "72 hours", "within 48 hours", "within 72 hours", "5 business days"]):
                        if status == ComplianceStatus.COMPLIANT:
                            status = ComplianceStatus.NON_COMPLIANT
                            val_status = "CORRECTED"
                            notes = (notes + " | " if notes else "") + "Ground truth correction: Contract breach notification timeframe exceeds 24-hour policy limit, corrected from COMPLIANT to NON_COMPLIANT."

                # Termination notice contradiction check (e.g. Policy: >= 30 days; Contract: 15 days, 7 days)
                if "30 days" in req_lower or "termination" in policy.name.lower():
                    if any(term in ev_plus_finding or term in doc_text_norm for term in ["15 days", "7 days", "10 days", "at least 15 days"]):
                        if status == ComplianceStatus.COMPLIANT:
                            status = ComplianceStatus.NON_COMPLIANT
                            val_status = "CORRECTED"
                            notes = (notes + " | " if notes else "") + "Ground truth correction: Contract termination notice is less than 30-day policy requirement, corrected from COMPLIANT to NON_COMPLIANT."

            verified_findings.append(
                ClauseFinding(
                    policy_id=f.policy_id,
                    policy_name=f.policy_name,
                    clause_reference=f.clause_reference,
                    status=status,
                    finding=f.finding,
                    severity=f.severity,
                    evidence=f.evidence,
                    validation_status=val_status,
                    validation_notes=notes
                )
            )

        return verified_findings

    @classmethod
    def parse_validation_response(
        cls,
        raw_text: str,
        initial_findings: List[ClauseFinding],
        policies: List[Policy]
    ) -> List[ClauseFinding]:
        policy_map = {p.policy_id.upper(): p for p in policies}
        validated_findings: List[ClauseFinding] = []

        try:
            data = robust_parse_json(raw_text, expected_keys=["validated_findings"])
            raw_findings = data.get("validated_findings", [])
            if not isinstance(raw_findings, list):
                raise ValueError("Expected 'validated_findings' to be a list")

            for item in raw_findings:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("policy_id", "")).strip().upper()
                matching_policy = policy_map.get(pid)

                status_str = str(item.get("status", "NOT_FOUND")).strip().upper()
                try:
                    status_enum = ComplianceStatus(status_str)
                except ValueError:
                    status_enum = ComplianceStatus.NOT_FOUND

                severity_str = str(item.get("severity", matching_policy.severity if matching_policy else "MEDIUM")).strip().upper()
                try:
                    severity_enum = Severity(severity_str)
                except ValueError:
                    severity_enum = Severity.MEDIUM

                p_name = item.get("policy_name") or (matching_policy.name if matching_policy else pid)

                validated_findings.append(
                    ClauseFinding(
                        policy_id=pid or (matching_policy.policy_id if matching_policy else "POL-UNKNOWN"),
                        policy_name=p_name,
                        clause_reference=item.get("clause_reference"),
                        status=status_enum,
                        finding=str(item.get("finding", "")),
                        severity=severity_enum,
                        evidence=item.get("evidence")
                    )
                )
            return validated_findings
        except Exception:
            return initial_findings

    @staticmethod
    def calculate_overall_status(findings: List[ClauseFinding]) -> str:
        has_critical_failure = False
        has_risk_finding = False

        for f in findings:
            if f.status in [ComplianceStatus.NON_COMPLIANT, ComplianceStatus.PARTIAL]:
                if f.severity == Severity.CRITICAL:
                    has_critical_failure = True
                else:
                    has_risk_finding = True
            elif f.status == ComplianceStatus.NOT_FOUND:
                if f.severity in [Severity.CRITICAL, Severity.HIGH]:
                    has_risk_finding = True

        if has_critical_failure:
            return "FAIL"
        elif has_risk_finding:
            return "RISK"
        else:
            return "PASS"
