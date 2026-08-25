import json
import re
from typing import List, Optional
from agent_framework import Agent
from src.agents.client_factory import get_chat_client
from src.models.schemas import (
    ExtractedDocument,
    ObligationResult,
    ClauseFinding,
    ComplianceStatus,
    Severity
)
from src.services.policy_service import Policy

POLICY_MATCHING_SYSTEM_INSTRUCTION = """You are a senior legal compliance auditor.
Your role is to evaluate extracted contract obligations and contract text against internal company compliance policies.

Use the structured obligations as your primary analysis source, cross-referencing the contract text for context.

For EVERY policy provided in the input, evaluate contract compliance and determine:
1. policy_id: Exact policy ID from input (e.g. POL-001, POL-002, POL-003, POL-004, POL-005). Do not omit any policy.
2. policy_name: Exact policy name from input.
3. clause_reference: Clause or section reference in contract (e.g. "Section 1", "Clause 4", or null if missing).
4. status: Must be EXACTLY one of ["COMPLIANT", "NON_COMPLIANT", "PARTIAL", "NOT_FOUND"]
   - COMPLIANT: Contract fully satisfies the policy requirement.
   - NON_COMPLIANT: Contract explicitly contradicts or violates the policy requirement (e.g., payment term is Net 90 when policy allows max Net 60).
   - PARTIAL: Contract addresses the topic but falls short of full requirement.
   - NOT_FOUND: Contract is completely silent on this policy requirement.
5. finding: Detailed explanation of why the contract is compliant, non-compliant, partial, or missing.
6. severity: Inherit policy severity from input ["CRITICAL", "HIGH", "MEDIUM", "LOW"].
7. evidence: Verbatim text snippet from contract supporting the finding (or null if NOT_FOUND).

CRITICAL RULES:
- Compare the ACTUAL numeric/substantive contract terms against policy limits. (e.g., Net 90 vs max Net 60 is NON_COMPLIANT).
- Do NOT mark COMPLIANT just because a topic is discussed.
- Never invent contract clauses or evidence.
- Return ONLY valid JSON formatted as: {"findings": [array of findings for ALL policies]}.
"""

from src.agents.json_utils import robust_parse_json

class PolicyClauseMatchingAgent:
    def __init__(self):
        client = get_chat_client()
        self.agent = Agent(
            client=client,
            name="PolicyClauseMatchingAgent",
            instructions=POLICY_MATCHING_SYSTEM_INSTRUCTION
        )

    @classmethod
    def build_matching_prompt(
        cls,
        doc: ExtractedDocument,
        obligations: Optional[ObligationResult],
        policies: List[Policy]
    ) -> str:
        policies_text = ""
        for p in policies:
            policies_text += (
                f"- Policy ID: {p.policy_id}\n"
                f"  Name: {p.name}\n"
                f"  Category: {p.category}\n"
                f"  Requirement: {p.requirement}\n"
                f"  Severity: {p.severity}\n"
                f"  Guidance: {p.guidance or 'N/A'}\n\n"
            )

        obl_list = []
        if obligations and obligations.obligations:
            for o in obligations.obligations:
                obl_list.append({
                    "obligation_id": o.obligation_id,
                    "description": o.description,
                    "responsible_party": o.responsible_party,
                    "clause_reference": o.clause_reference,
                    "due_date": o.due_date,
                    "sla": o.sla,
                    "penalty": o.penalty,
                    "conditions": o.conditions,
                    "relevant_evidence": o.relevant_evidence
                })

        obl_json = json.dumps(obl_list, indent=2) if obl_list else "[]"
        obl_summary = obligations.summary if obligations else "None"

        return f"""Contract Document Name: {doc.file_name}

=== PRIMARY STRUCTURED OBLIGATIONS (Extracted in Step 3) ===
Obligations Summary: {obl_summary}
Obligations List ({len(obl_list)} items):
{obl_json}

=== SUPPORTING CONTRACT FULL TEXT ===
{doc.text}

=== POLICIES TO EVALUATE (Provide findings for every single policy) ===
{policies_text}
"""

    async def match_policies(
        self,
        doc: ExtractedDocument,
        obligations: ObligationResult,
        policies: List[Policy]
    ) -> List[ClauseFinding]:
        prompt = self.build_matching_prompt(doc, obligations, policies)
        from src.agents.retry_utils import execute_with_retry
        response = await execute_with_retry(self.agent.run, prompt)
        response_text = getattr(response, "text", str(response)).strip()
        return self.parse_findings_response(response_text, policies)

    @classmethod
    def parse_findings_response(cls, raw_text: str, policies: List[Policy]) -> List[ClauseFinding]:
        findings: List[ClauseFinding] = []
        policy_map = {p.policy_id.upper(): p for p in policies}
        found_ids = set()

        try:
            data = robust_parse_json(raw_text, expected_keys=["findings"])
            raw_findings = data.get("findings", [])
            if not isinstance(raw_findings, list):
                raise ValueError("Expected 'findings' to be a list in JSON response")

            for item in raw_findings:
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

                if matching_policy:
                    found_ids.add(pid)

                findings.append(
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

            for p in policies:
                if p.policy_id.upper() not in found_ids:
                    findings.append(
                        ClauseFinding(
                            policy_id=p.policy_id,
                            policy_name=p.name,
                            clause_reference=None,
                            status=ComplianceStatus.NOT_FOUND,
                            finding="Policy requirement not evaluated by agent.",
                            severity=Severity[p.severity] if p.severity in Severity.__members__ else Severity.MEDIUM,
                            evidence=None
                        )
                    )

            return findings
        except Exception as e:
            fallback_findings: List[ClauseFinding] = []
            for p in policies:
                fallback_findings.append(
                    ClauseFinding(
                        policy_id=p.policy_id,
                        policy_name=p.name,
                        status=ComplianceStatus.NOT_FOUND,
                        finding=f"Policy matching fallback due to error: {str(e)}",
                        severity=Severity[p.severity] if p.severity in Severity.__members__ else Severity.MEDIUM,
                        evidence=None
                    )
                )
            return fallback_findings
