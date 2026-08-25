import json
import re
from typing import Optional
from agent_framework import Agent
from src.agents.client_factory import get_chat_client
from src.models.schemas import ExtractedDocument, ClassificationResult, DocumentType

CLASSIFICATION_SYSTEM_INSTRUCTION = """You are a senior contract classification expert.
Your job is to analyze document content and determine:
1. document_type: Must be one of ["Contract", "Purchase Order", "Invoice", "Policy", "Other"]
2. is_contract: boolean (true if the document is a legally binding contract, agreement, master service agreement, scope of work, amendment, or contract addendum; false otherwise)
3. confidence: float between 0.0 and 1.0
4. reasoning: concise explanation supporting the decision.

CRITICAL RULES:
- Never hallucinate details not in the text.
- Return ONLY valid JSON with keys: "document_type", "is_contract", "confidence", "reasoning".
- Do not include markdown code fence formatting outside the JSON object.
"""

class ClassificationAgent:
    def __init__(self):
        client = get_chat_client()
        self.agent = Agent(
            client=client,
            name="ClassificationAgent",
            instructions=CLASSIFICATION_SYSTEM_INSTRUCTION
        )

    def _prepare_document_content(self, doc: ExtractedDocument) -> str:
        if not doc.text or not doc.text.strip():
            return "EMPTY DOCUMENT"

        total_length = len(doc.text)
        # For documents within 8000 characters, pass the full text
        if total_length <= 8000:
            return doc.text

        # For long documents, extract structured cross-document sections
        # 1. Beginning (headers, preamble, opening recitals)
        head_chunk = doc.text[:3500]
        # 2. Tail (final clauses, signature blocks, exhibits)
        tail_chunk = doc.text[-3500:]
        # 3. Middle (sample from the middle third of the document)
        mid_start = (total_length // 2) - 1000
        mid_chunk = doc.text[mid_start: mid_start + 2000]

        return (
            f"--- [DOCUMENT SECTION: BEGINNING (chars 0-{len(head_chunk)})] ---\n"
            f"{head_chunk}\n\n"
            f"--- [DOCUMENT SECTION: MIDDLE (chars {mid_start}-{mid_start + len(mid_chunk)})] ---\n"
            f"{mid_chunk}\n\n"
            f"--- [DOCUMENT SECTION: CONCLUSION & SIGNATURES (chars {total_length - len(tail_chunk)}-{total_length})] ---\n"
            f"{tail_chunk}"
        )

    async def classify(self, doc: ExtractedDocument) -> ClassificationResult:
        from src.agents.retry_utils import execute_with_retry
        content = self._prepare_document_content(doc)
        prompt = f"Document File Name: {doc.file_name}\nTotal Character Count: {len(doc.text) if doc.text else 0}\n\nDocument Content Analysis:\n{content}"
        
        response = await execute_with_retry(self.agent.run, prompt)
        response_text = getattr(response, "text", str(response)).strip()
        
        return self.parse_classification_response(response_text, content)

    @staticmethod
    def parse_classification_response(raw_text: str, content: str = "") -> ClassificationResult:
        from src.config import config
        from src.agents.json_utils import robust_parse_json
        try:
            data = robust_parse_json(raw_text, expected_keys=["document_type", "is_contract"])
            # Map document_type string to DocumentType enum safely
            doc_type_str = data.get("document_type", "Other")
            try:
                doc_type = DocumentType(doc_type_str)
            except ValueError:
                doc_type = DocumentType.OTHER

            # Validate and clamp confidence score
            raw_conf = data.get("confidence")
            try:
                if raw_conf is None:
                    confidence = 0.0
                else:
                    confidence = float(raw_conf)
                    confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.0

            is_contract = bool(data.get("is_contract", False))
            reasoning = str(data.get("reasoning", "Classification completed."))

            # Apply confidence thresholds
            threshold = getattr(config, "classification_confidence_threshold", 0.65)
            is_confident = confidence >= threshold
            needs_review = not is_confident
            status = "CONFIDENT" if is_confident else "UNCERTAIN"

            return ClassificationResult(
                document_type=doc_type,
                is_contract=is_contract,
                confidence=confidence,
                reasoning=reasoning,
                is_confident=is_confident,
                needs_review=needs_review,
                status=status
            )
        except Exception as e:
            # Safe fallback if malformed output: explicit ERROR status, no keyword matching
            return ClassificationResult(
                document_type=DocumentType.OTHER,
                is_contract=False,
                confidence=0.0,
                reasoning=f"Classification output parsing error: {str(e)}",
                is_confident=False,
                needs_review=True,
                status="ERROR"
            )
