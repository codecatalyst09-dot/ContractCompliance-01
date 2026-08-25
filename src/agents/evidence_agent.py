import json
import re
from typing import List, Optional
from agent_framework import Agent
from src.agents.client_factory import get_chat_client
from src.models.schemas import (
    ExtractedDocument,
    ClauseFinding,
    ComplianceStatus,
    RiskScore,
    EvidenceItem,
    EvidencePack
)
from src.services.policy_service import Policy

EVIDENCE_SYSTEM_INSTRUCTION = """You are a senior compliance evidence officer and legal documentation specialist.

Your job is to:
1. Generate a complete evidence pack for ALL policy findings (COMPLIANT, NON_COMPLIANT, PARTIAL, and NOT_FOUND).
2. For each policy finding, produce an EvidenceItem containing:
   - policy_id: Exact policy ID (e.g. POL-001)
   - clause_reference: Section or clause reference in the contract (or null if missing)
   - evidence: Verbatim text snippet from the contract supporting the finding (or "NOT FOUND IN CONTRACT" if missing)
   - source: Document file name
   - page_number: Page number where evidence was found (or null if unknown)
3. For non-compliant, partial, or missing policies, generate specific, actionable remediation recommendations.
4. For fully compliant policies, provide a brief compliance confirmation note.

CRITICAL RULES:
- Never invent evidence. Evidence must be verbatim text from the contract.
- If a clause is missing, clearly state evidence as "NOT FOUND IN CONTRACT".
- Return ONLY valid JSON formatted as:
{
  "evidence_items": [
    {
      "policy_id": "POL-001",
      "clause_reference": "Section 1",
      "evidence": "Verbatim contract text here...",
      "source": "contract.txt",
      "page_number": 1
    }
  ],
  "recommendations": [
    "Specific remediation recommendation or compliance confirmation..."
  ]
}
"""

def extract_json_block(text: str) -> str:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return text

from src.services.evidence_visualizer import capture_evidence_jpg

class EvidenceGenerationAgent:
    def __init__(self):
        client = get_chat_client()
        self.agent = Agent(
            client=client,
            name="EvidenceGenerationAgent",
            instructions=EVIDENCE_SYSTEM_INSTRUCTION
        )

    async def generate_evidence(
        self,
        doc: ExtractedDocument,
        findings: List[ClauseFinding],
        risk: RiskScore,
        policies: List[Policy],
        run_id: Optional[str] = None
    ) -> EvidencePack:
        current_run_id = run_id or doc.metadata.run_id or "run"
        findings_by_id = {f.policy_id: f for f in findings}
        policies_by_id = {p.policy_id: p for p in policies}

        # Build findings summary for all policies (both passed and failed/partial)
        findings_summary = json.dumps(
            [f.model_dump() for f in findings], indent=2
        )

        prompt = f"""Contract Document: {doc.file_name}
Risk Score: {risk.score}/100 ({risk.risk_level.value} risk)

Contract Full Text:
{doc.text}

All Policy Findings (Passed, Partial, Failed, Not Found):
{findings_summary}
"""
        from src.agents.retry_utils import execute_with_retry
        response = await execute_with_retry(self.agent.run, prompt)
        response_text = getattr(response, "text", str(response)).strip()
        evidence_items, recommendations = self.parse_evidence_response(
            raw_text=response_text,
            doc=doc,
            findings=findings,
            policies=policies,
            run_id=current_run_id
        )

        return EvidencePack(
            evidence_items=evidence_items,
            recommendations=recommendations
        )

    @classmethod
    def parse_evidence_response(
        cls,
        raw_text: str,
        doc: ExtractedDocument,
        findings: List[ClauseFinding],
        policies: List[Policy],
        run_id: Optional[str] = None
    ) -> tuple[List[EvidenceItem], List[str]]:
        from src.agents.json_utils import robust_parse_json
        current_run_id = run_id or (doc.metadata.run_id if doc.metadata else "run")
        findings_by_id = {f.policy_id.upper(): f for f in findings}
        policies_by_id = {p.policy_id.upper(): p for p in policies}
        known_policy_ids = set(findings_by_id.keys()) | set(policies_by_id.keys())

        evidence_items: List[EvidenceItem] = []
        recommendations: List[str] = []

        try:
            data = robust_parse_json(raw_text, expected_keys=["evidence_items"])

            for item in data.get("evidence_items", []):
                if not isinstance(item, dict):
                    continue
                pol_id = str(item.get("policy_id", "")).strip()
                clause_ref = item.get("clause_reference")
                ev_text = str(item.get("evidence", "NOT FOUND IN CONTRACT"))
                page_num = item.get("page_number")
                pol_key = pol_id.upper()

                if pol_key in known_policy_ids:
                    finding = findings_by_id.get(pol_key)
                    # Use actual status from finding, or NOT_FOUND if policy known but no finding - NEVER default to COMPLIANT
                    status_str = finding.status.value if finding else "NOT_FOUND"
                    policy_name = (
                        finding.policy_name
                        if finding
                        else (policies_by_id[pol_key].name if pol_key in policies_by_id else pol_id)
                    )
                else:
                    # Unknown/unrecognized policy ID returned by AI
                    status_str = "INVALID_POLICY"
                    policy_name = f"Unknown Policy ({pol_id})"
                    recommendations.append(f"[WARNING] Discarded unrecognized policy evidence for ID '{pol_id}'.")

                doc_path = doc.metadata.file_path if doc.metadata else ""
                img_path = capture_evidence_jpg(
                    doc_path=doc_path,
                    run_id=current_run_id,
                    policy_id=pol_id,
                    policy_name=policy_name,
                    status=status_str,
                    clause_ref=clause_ref,
                    evidence_text=ev_text,
                    page_number=page_num
                )

                evidence_items.append(
                    EvidenceItem(
                        policy_id=pol_id,
                        clause_reference=clause_ref,
                        evidence=ev_text,
                        source=str(item.get("source", doc.file_name)),
                        page_number=page_num,
                        image_path=img_path
                    )
                )

            ai_recs = [
                str(r) for r in data.get("recommendations", [])
                if r and len(str(r).strip()) > 0
            ]
            recommendations.extend(ai_recs)

        except Exception as e:
            # Fallback: preserve evidence items from findings directly with accurate statuses
            for f in findings:
                doc_path = doc.metadata.file_path if doc.metadata else ""
                img_path = capture_evidence_jpg(
                    doc_path=doc_path,
                    run_id=current_run_id,
                    policy_id=f.policy_id,
                    policy_name=f.policy_name,
                    status=f.status.value,
                    clause_ref=f.clause_reference,
                    evidence_text=f.evidence or "NOT FOUND IN CONTRACT",
                    page_number=None
                )
                evidence_items.append(
                    EvidenceItem(
                        policy_id=f.policy_id,
                        clause_reference=f.clause_reference,
                        evidence=f.evidence or "NOT FOUND IN CONTRACT",
                        source=doc.file_name,
                        page_number=None,
                        image_path=img_path
                    )
                )
            recommendations = [
                f"[{f.status.value}] {f.policy_name} ({f.policy_id}): {f.finding}"
                for f in findings
                if f.status != ComplianceStatus.COMPLIANT
            ] or ["All evaluated policies are fully compliant."]

        return evidence_items, recommendations


