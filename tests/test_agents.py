import pytest
import asyncio
from src.ingestion.document_loader import load_and_extract_document
from src.agents.classification_agent import ClassificationAgent
from src.agents.obligation_agent import ObligationExtractionAgent
from src.agents.policy_agent import PolicyClauseMatchingAgent
from src.agents.validation_agent import ComplianceValidationAgent
from src.services.policy_service import PolicyService
from src.models.schemas import DocumentType, ComplianceStatus

def test_classification_contract_document():
    async def _test():
        doc = load_and_extract_document("documents/sample_contract.txt")
        agent = ClassificationAgent()
        result = await agent.classify(doc)
        assert result.is_contract is True
        assert result.document_type == DocumentType.CONTRACT
        assert result.confidence >= 0.7
        assert len(result.reasoning) > 0
    asyncio.run(_test())

def test_classification_non_contract_document():
    async def _test():
        doc = load_and_extract_document("documents/sample_non_contract.txt")
        agent = ClassificationAgent()
        result = await agent.classify(doc)
        assert result.is_contract is False
        assert result.document_type == DocumentType.INVOICE
        assert len(result.reasoning) > 0
    asyncio.run(_test())

def test_classification_long_contract_identifying_language_after_4000_chars():
    async def _test():
        from src.models.schemas import ExtractedDocument, DocumentMetadata, FileType
        # Construct a document > 9000 chars where the first 5000 chars are non-contract product specs
        prefix_prose = "Product Specification Overview and Architecture Guidelines.\n" * 90  # ~5400 chars
        contract_body = """
MASTER SERVICES AND LICENSING AGREEMENT
This legally binding Agreement is entered into by Alpha Corp and Beta Inc.
Both parties agree to the following terms, obligations, payment conditions, and confidentiality covenants.
IN WITNESS WHEREOF, the parties hereto have executed this Agreement by their duly authorized representatives.
"""
        full_text = prefix_prose + "\n" + contract_body
        assert len(full_text) > 5500
        # Notice identifying terms only appear after char 5000
        assert "MASTER SERVICES AND LICENSING AGREEMENT" not in full_text[:4000]

        doc = ExtractedDocument(
            document_id="doc-long-test",
            file_name="long_enterprise_agreement.txt",
            metadata=DocumentMetadata(
                run_id="run-test",
                file_name="long_enterprise_agreement.txt",
                file_path="documents/long_enterprise_agreement.txt",
                file_type=FileType.TXT,
                file_size=len(full_text),
                file_hash="0"*64,
                ingestion_timestamp="2026-08-24T00:00:00Z"
            ),
            text=full_text
        )
        agent = ClassificationAgent()
        result = await agent.classify(doc)
        assert result.is_contract is True
        assert result.document_type == DocumentType.CONTRACT
        assert result.confidence >= 0.6
        assert result.is_confident is True
        assert result.needs_review is False
    asyncio.run(_test())

def test_classification_confidence_validation():
    # 1. High confidence response
    high_conf_json = '{"document_type": "Contract", "is_contract": true, "confidence": 0.95, "reasoning": "Standard MSA contract"}'
    res_high = ClassificationAgent.parse_classification_response(high_conf_json)
    assert res_high.is_contract is True
    assert res_high.confidence == 0.95
    assert res_high.is_confident is True
    assert res_high.needs_review is False
    assert res_high.status == "CONFIDENT"

    # 2. Low confidence response
    low_conf_json = '{"document_type": "Other", "is_contract": false, "confidence": 0.40, "reasoning": "Unclear informal note"}'
    res_low = ClassificationAgent.parse_classification_response(low_conf_json)
    assert res_low.is_contract is False
    assert res_low.confidence == 0.40
    assert res_low.is_confident is False
    assert res_low.needs_review is True
    assert res_low.status == "UNCERTAIN"

    # 3. Malformed/missing/out of range confidence
    missing_conf_json = '{"document_type": "Invoice", "is_contract": false, "confidence": null, "reasoning": "Billing invoice"}'
    res_missing = ClassificationAgent.parse_classification_response(missing_conf_json)
    assert res_missing.confidence == 0.0
    assert res_missing.is_confident is False
    assert res_missing.needs_review is True

    out_of_range_json = '{"document_type": "Contract", "is_contract": true, "confidence": 1.5, "reasoning": "Contract"}'
    res_out = ClassificationAgent.parse_classification_response(out_of_range_json)
    assert res_out.confidence == 1.0
    assert res_out.is_confident is True

    invalid_str_conf = '{"document_type": "Contract", "is_contract": true, "confidence": "very_high", "reasoning": "Contract"}'
    res_str = ClassificationAgent.parse_classification_response(invalid_str_conf)
    assert res_str.confidence == 0.0
    assert res_str.is_confident is False
    assert res_str.needs_review is True

def test_classification_malformed_json_and_no_keyword_hallucination():
    # Test completely broken JSON
    broken_output = "I think this document might be an AGREEMENT between parties, but here is no valid JSON."
    res_broken = ClassificationAgent.parse_classification_response(broken_output, content="this is not our agreement")
    # Must NOT classify as contract just because "AGREEMENT" is present in text or content
    assert res_broken.is_contract is False
    assert res_broken.document_type == DocumentType.OTHER
    assert res_broken.status == "ERROR"
    assert res_broken.confidence == 0.0
    assert "error" in res_broken.reasoning.lower()

    # Test valid JSON embedded in markdown fences and conversational intro
    chatty_output = """Sure! Here is the classification result:
```json
{
  "document_type": "Invoice",
  "is_contract": false,
  "confidence": 0.92,
  "reasoning": "Payment request invoice for software services."
}
```
Hope that helps!"""
    res_chatty = ClassificationAgent.parse_classification_response(chatty_output, content="Invoice #123 per prior agreement")
    assert res_chatty.is_contract is False
    assert res_chatty.document_type == DocumentType.INVOICE
    assert res_chatty.confidence == 0.92
    assert res_chatty.status == "CONFIDENT"
    assert res_chatty.is_confident is True

def test_obligation_extraction():
    async def _test():
        doc = load_and_extract_document("documents/sample_contract.txt")
        agent = ObligationExtractionAgent()
        result = await agent.extract_obligations(doc)
        assert len(result.obligations) > 0
        assert result.is_success is True
        assert result.extraction_status == "SUCCESS"
        payment_ob = next((o for o in result.obligations if "payment" in o.description.lower() or "pay" in o.description.lower()), None)
        assert payment_ob is not None
        assert payment_ob.is_explicit is True
    asyncio.run(_test())

def test_obligation_extraction_failure_vs_zero_obligations():
    # Case A: Successfully extracted 0 obligations
    valid_zero_json = '{"obligations": [], "summary": "Informational document with zero contractual obligations."}'
    res_zero = ObligationExtractionAgent.parse_obligation_response(valid_zero_json)
    assert res_zero.is_success is True
    assert res_zero.extraction_status == "SUCCESS"
    assert len(res_zero.obligations) == 0
    assert res_zero.error_message is None

    # Case B: Failed extraction due to broken response / malformed payload
    broken_payload = "Error 500: Model failed to generate response."
    res_failed = ObligationExtractionAgent.parse_obligation_response(broken_payload)
    assert res_failed.is_success is False
    assert res_failed.extraction_status == "FAILED"
    assert len(res_failed.obligations) == 0
    assert res_failed.error_message is not None
    assert "failed" in res_failed.summary.lower()

    # Case C: Invalid schema (obligations is string instead of array)
    invalid_schema = '{"obligations": "None found", "summary": "Done"}'
    res_inv = ObligationExtractionAgent.parse_obligation_response(invalid_schema)
    assert res_inv.is_success is False
    assert res_inv.extraction_status == "FAILED"

def test_policy_clause_matching():
    async def _test():
        doc = load_and_extract_document("documents/sample_contract.txt")
        obl_agent = ObligationExtractionAgent()
        obligations = await obl_agent.extract_obligations(doc)
        policy_service = PolicyService()
        policies = policy_service.get_all_policies()
        policy_agent = PolicyClauseMatchingAgent()
        findings = await policy_agent.match_policies(doc, obligations, policies)
        assert len(findings) == len(policies)
        pol1 = next((f for f in findings if f.policy_id == "POL-001"), None)
        assert pol1 is not None
        assert pol1.status in [ComplianceStatus.COMPLIANT, ComplianceStatus.NON_COMPLIANT, ComplianceStatus.PARTIAL, ComplianceStatus.NOT_FOUND]
    asyncio.run(_test())

def test_policy_matching_uses_extracted_obligations():
    from src.models.schemas import Obligation, ObligationResult, ExtractedDocument, DocumentMetadata, FileType
    from src.services.policy_service import Policy

    doc = ExtractedDocument(
        document_id="doc-obl-test",
        file_name="vendor_agreement.txt",
        metadata=DocumentMetadata(
            run_id="run-obl",
            file_name="vendor_agreement.txt",
            file_path="documents/vendor_agreement.txt",
            file_type=FileType.TXT,
            file_size=200,
            file_hash="0"*64,
            ingestion_timestamp="2026-08-24T00:00:00Z"
        ),
        text="Section 1. Payment within Net 90 days. Section 2. Liability capped at $50k."
    )

    obligations = ObligationResult(
        obligations=[
            Obligation(
                obligation_id="OBL-001",
                description="Customer shall pay within Net 90 days",
                responsible_party="Customer",
                clause_reference="Section 1",
                due_date="Net 90 days",
                sla=None,
                penalty="1.5% interest per month",
                conditions=None,
                relevant_evidence="Section 1. Payment within Net 90 days.",
                is_explicit=True
            ),
            Obligation(
                obligation_id="OBL-002",
                description="Liability aggregate cap $50,000",
                responsible_party="Both Parties",
                clause_reference="Section 2",
                due_date=None,
                sla=None,
                penalty=None,
                conditions=None,
                relevant_evidence="Section 2. Liability capped at $50k.",
                is_explicit=True
            )
        ],
        summary="Two primary operational obligations extracted.",
        extraction_status="SUCCESS",
        is_success=True
    )

    policies = [
        Policy(
            policy_id="POL-001",
            name="Payment Terms",
            category="Financial",
            description="Payment policy",
            requirement="Max Net 60 days",
            severity="HIGH"
        )
    ]

    prompt = PolicyClauseMatchingAgent.build_matching_prompt(doc, obligations, policies)

    # Prove that extracted obligations are in the prompt
    assert "PRIMARY STRUCTURED OBLIGATIONS" in prompt
    assert "OBL-001" in prompt
    assert "Net 90 days" in prompt
    assert "OBL-002" in prompt
    assert "$50,000" in prompt
    assert "1.5% interest" in prompt
    assert "POL-001" in prompt

def test_compliance_validation():
    async def _test():
        doc = load_and_extract_document("documents/sample_contract.txt")
        obl_agent = ObligationExtractionAgent()
        obligations = await obl_agent.extract_obligations(doc)
        policy_service = PolicyService()
        policies = policy_service.get_all_policies()
        policy_agent = PolicyClauseMatchingAgent()
        initial_findings = await policy_agent.match_policies(doc, obligations, policies)
        val_agent = ComplianceValidationAgent()
        result = await val_agent.validate(doc, obligations, initial_findings, policies)
        assert len(result.findings) == len(policies)
        assert result.overall_status in ["PASS", "RISK", "FAIL"]
        calc_status = val_agent.calculate_overall_status(result.findings)
        assert result.overall_status == calc_status
    asyncio.run(_test())

def test_unknown_evidence_policy_id_never_defaults_to_compliant(monkeypatch):
    from src.agents.evidence_agent import EvidenceGenerationAgent
    from src.models.schemas import ClauseFinding, Severity, ExtractedDocument, DocumentMetadata, FileType
    from src.services.policy_service import Policy

    # Mock capture_evidence_jpg to return a test path and record called status
    captured_statuses = []
    def mock_capture(*args, **kwargs):
        captured_statuses.append(kwargs.get("status"))
        return "outputs/evidence_images/test.jpg"

    import src.agents.evidence_agent as ev_module
    monkeypatch.setattr(ev_module, "capture_evidence_jpg", mock_capture)

    known_findings = [
        ClauseFinding(
            policy_id="POL-001",
            policy_name="Payment Terms",
            clause_reference="Section 1",
            status=ComplianceStatus.NON_COMPLIANT,
            finding="Net 90 payment is non compliant",
            severity=Severity.HIGH,
            evidence="Net 90 days"
        )
    ]
    known_policies = [
        Policy(
            policy_id="POL-001",
            name="Payment Terms",
            category="Financial",
            description="Payment terms policy",
            requirement="Max Net 60",
            severity="HIGH",
            guidance="Net 30 preferred"
        )
    ]

    doc = ExtractedDocument(
        document_id="doc-test",
        file_name="contract.txt",
        metadata=DocumentMetadata(
            run_id="run-1",
            file_name="contract.txt",
            file_path="documents/contract.txt",
            file_type=FileType.TXT,
            file_size=100,
            file_hash="0"*64,
            ingestion_timestamp="2026-08-24T00:00:00Z"
        ),
        text="Sample text Net 90"
    )

    # Response has evidence for known POL-001 and unknown hallucinated POL-999
    ai_response = """{
        "evidence_items": [
            {
                "policy_id": "POL-001",
                "clause_reference": "Section 1",
                "evidence": "Net 90 days",
                "source": "contract.txt",
                "page_number": 1
            },
            {
                "policy_id": "POL-999",
                "clause_reference": "Section 99",
                "evidence": "Hallucinated policy evidence",
                "source": "contract.txt",
                "page_number": 1
            }
        ],
        "recommendations": ["Remediate POL-001"]
    }"""

    items, recs = EvidenceGenerationAgent.parse_evidence_response(
        raw_text=ai_response,
        doc=doc,
        findings=known_findings,
        policies=known_policies,
        run_id="run-1"
    )

    assert len(items) == 2
    # Known finding must preserve NON_COMPLIANT
    assert captured_statuses[0] == "NON_COMPLIANT"
    # Unknown policy must NOT be COMPLIANT!
    assert captured_statuses[1] != "COMPLIANT"
    assert captured_statuses[1] == "INVALID_POLICY"
    assert any("POL-999" in r for r in recs)

def test_ground_truth_contradiction_detection_and_correction():
    from src.agents.validation_agent import ComplianceValidationAgent
    from src.models.schemas import ClauseFinding, Severity, ExtractedDocument, DocumentMetadata, FileType
    from src.services.policy_service import Policy

    doc = ExtractedDocument(
        document_id="doc-gt-test",
        file_name="gt_contract.txt",
        metadata=DocumentMetadata(
            run_id="run-gt",
            file_name="gt_contract.txt",
            file_path="documents/gt_contract.txt",
            file_type=FileType.TXT,
            file_size=300,
            file_hash="0"*64,
            ingestion_timestamp="2026-08-24T00:00:00Z"
        ),
        text="Section 1. Payment shall be made within Net 90 days. Section 2. Security breach notice within 48 hours."
    )

    policies = [
        Policy(
            policy_id="POL-001",
            name="Payment Terms Policy",
            category="Financial",
            description="Payment terms",
            requirement="Payment must not exceed Net 60 days",
            severity="HIGH"
        ),
        Policy(
            policy_id="POL-004",
            name="Data Security Breach Notification",
            category="Security",
            description="Breach notice",
            requirement="Must notify within 24 hours of breach",
            severity="CRITICAL"
        ),
        Policy(
            policy_id="POL-003",
            name="Confidentiality Policy",
            category="Legal",
            description="Confidentiality",
            requirement="Mutual 5-year confidentiality",
            severity="MEDIUM"
        )
    ]

    # Simulating flawed AI findings where:
    # 1. AI falsely claimed Net 90 is COMPLIANT with max Net 60 policy
    # 2. AI falsely claimed 48 hours is COMPLIANT with 24 hours policy
    # 3. AI quoted a hallucinated phrase not present in the contract
    flawed_findings = [
        ClauseFinding(
            policy_id="POL-001",
            policy_name="Payment Terms Policy",
            clause_reference="Section 1",
            status=ComplianceStatus.COMPLIANT,  # Contradiction!
            finding="AI falsely marked compliant",
            severity=Severity.HIGH,
            evidence="Payment shall be made within Net 90 days."
        ),
        ClauseFinding(
            policy_id="POL-004",
            policy_name="Data Security Breach Notification",
            clause_reference="Section 2",
            status=ComplianceStatus.COMPLIANT,  # Contradiction!
            finding="AI falsely marked compliant",
            severity=Severity.CRITICAL,
            evidence="Security breach notice within 48 hours."
        ),
        ClauseFinding(
            policy_id="POL-003",
            policy_name="Confidentiality Policy",
            clause_reference="Section 99",
            status=ComplianceStatus.COMPLIANT,
            finding="Mutual confidentiality agreed",
            severity=Severity.MEDIUM,
            evidence="Invented clause that does not exist anywhere in contract text"
        )
    ]

    checked = ComplianceValidationAgent.apply_ground_truth_cross_checks(doc, flawed_findings, policies)

    # 1. POL-001 must be corrected from COMPLIANT to NON_COMPLIANT
    pol1 = next(f for f in checked if f.policy_id == "POL-001")
    assert pol1.status == ComplianceStatus.NON_COMPLIANT
    assert pol1.validation_status == "CORRECTED"
    assert "Net > 60" in pol1.validation_notes

    # 2. POL-004 must be corrected from COMPLIANT to NON_COMPLIANT
    pol4 = next(f for f in checked if f.policy_id == "POL-004")
    assert pol4.status == ComplianceStatus.NON_COMPLIANT
    assert pol4.validation_status == "CORRECTED"
    assert "24-hour" in pol4.validation_notes

    # 3. POL-003 must be flagged as unverified evidence
    pol3 = next(f for f in checked if f.policy_id == "POL-003")
    assert pol3.validation_status == "UNVERIFIED_EVIDENCE"
    assert "not found verbatim" in pol3.validation_notes
