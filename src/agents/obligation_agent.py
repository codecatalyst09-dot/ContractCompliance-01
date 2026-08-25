import json
import re
from typing import Optional, List
from agent_framework import Agent
from src.agents.client_factory import get_chat_client
from src.models.schemas import ExtractedDocument, Obligation, ObligationResult

OBLIGATION_SYSTEM_INSTRUCTION = """You are a legal document analyst specializing in contract obligation and template structure extraction.
Your task is to identify and extract all explicit contractual obligations and structural components from the contract text (including core obligations, recitals, payment terms, termination rules, liability provisions, governing law, and execution/signature blocks).

For each obligation or structural component found, extract:
- obligation_id: A unique identifier like "OBL-001", "OBL-002", etc.
- description: Clear summary of the contractual duty, structural clause, or requirement.
- responsible_party: Who must perform the obligation (e.g. "Client", "Provider", "Both Parties", or null if unspecified).
- clause_reference: Section name or number where found (e.g. "Section 1", "Clause 3", "Execution Block", or null).
- due_date: Specific timeframe or deadline (e.g. "Net 90 days", "within 48 hours", or null).
- sla: Service level agreement commitment if applicable, else null.
- penalty: Financial or legal penalty for failure if specified, else null.
- conditions: Triggering conditions or prerequisites if specified, else null.
- relevant_evidence: Exact text snippet or sentence from the contract supporting this obligation or structural clause.
- is_explicit: true if explicitly written in text, false if inferred.

CRITICAL RULES:
- Never invent or hallucinate clauses, dates, parties, penalties, or evidence.
- If an item (like penalty or SLA) is not mentioned in the contract, set its value to null.
- Return ONLY valid JSON with keys: "obligations" (array of obligation objects) and "summary" (brief overall summary of contractual obligations).
- Do not include markdown code fence formatting outside the JSON object.
"""

class ObligationExtractionAgent:
    def __init__(self):
        client = get_chat_client()
        self.agent = Agent(
            client=client,
            name="ObligationExtractionAgent",
            instructions=OBLIGATION_SYSTEM_INSTRUCTION
        )

    async def extract_obligations(self, doc: ExtractedDocument) -> ObligationResult:
        from src.agents.retry_utils import execute_with_retry
        prompt = f"Contract Document Name: {doc.file_name}\n\nContract Text:\n{doc.text}"
        
        response = await execute_with_retry(self.agent.run, prompt)
        response_text = getattr(response, "text", str(response)).strip()
        return self.parse_obligation_response(response_text)

    @staticmethod
    def parse_obligation_response(raw_text: str) -> ObligationResult:
        from src.agents.json_utils import robust_parse_json
        try:
            data = robust_parse_json(raw_text, expected_keys=["obligations"])
            raw_obligations = data.get("obligations", [])
            if not isinstance(raw_obligations, list):
                raise ValueError("Expected 'obligations' to be a list in JSON response")

            obligations_list: List[Obligation] = []

            for idx, item in enumerate(raw_obligations, start=1):
                if not isinstance(item, dict):
                    continue
                obl_id = item.get("obligation_id") or f"OBL-{idx:03d}"
                obligations_list.append(
                    Obligation(
                        obligation_id=obl_id,
                        description=str(item.get("description", "")),
                        responsible_party=item.get("responsible_party"),
                        clause_reference=item.get("clause_reference"),
                        due_date=item.get("due_date"),
                        sla=item.get("sla"),
                        penalty=item.get("penalty"),
                        conditions=item.get("conditions"),
                        relevant_evidence=item.get("relevant_evidence"),
                        is_explicit=bool(item.get("is_explicit", True))
                    )
                )

            return ObligationResult(
                obligations=obligations_list,
                summary=str(data.get("summary", f"Extracted {len(obligations_list)} obligations.")),
                extraction_status="SUCCESS",
                is_success=True,
                error_message=None
            )
        except Exception as e:
            return ObligationResult(
                obligations=[],
                summary=f"Obligation extraction failed: {str(e)}",
                extraction_status="FAILED",
                is_success=False,
                error_message=str(e)
            )
