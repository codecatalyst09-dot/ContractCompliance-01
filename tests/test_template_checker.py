from src.models.schemas import DocumentMetadata, ExtractedDocument, FileType, ComplianceStatus
from src.services.policy_service import Policy
from src.services.template_checker import evaluate_template_policy


def _doc_with_text(text: str) -> ExtractedDocument:
    return ExtractedDocument(
        document_id="doc1234567890abcd",
        file_name="sample_contract.txt",
        metadata=DocumentMetadata(
            run_id="run-1",
            file_name="sample_contract.txt",
            file_path="documents/sample_contract.txt",
            file_type=FileType.TXT,
            file_size=100,
            file_hash="a" * 64,
            ingestion_timestamp="2026-01-01T00:00:00Z",
        ),
        pages=[],
        text=text,
        tables=[],
    )


def _template_policy() -> Policy:
    return Policy(
        policy_id="POL-006",
        name="Standard Contract Template & Mandatory Sections Policy",
        category="Template & Legal Structure",
        description="Checks required contract structure",
        requirement="Must include mandatory sections and template completeness",
        severity="HIGH",
        guidance=None,
    )


def test_template_checker_detects_compliant_template():
    text = """
    This Agreement is made between Client and Provider with an Effective Date.
    Scope of Services and Deliverables are listed below.
    Payment and Fees shall be invoiced on Net 30 terms.
    Term and Termination rights are defined.
    Confidentiality obligations survive termination.
    Limitation of Liability excludes consequential damages.
    Governing Law and Jurisdiction are set to India.
    Signed by authorized signatory in witness whereof.
    """
    finding = evaluate_template_policy(_doc_with_text(text), [_template_policy()])
    assert finding is not None
    assert finding.status == ComplianceStatus.COMPLIANT


def test_template_checker_detects_missing_sections():
    text = "This document only mentions payment fees and invoice terms."
    finding = evaluate_template_policy(_doc_with_text(text), [_template_policy()])
    assert finding is not None
    assert finding.status in [ComplianceStatus.NON_COMPLIANT, ComplianceStatus.PARTIAL, ComplianceStatus.NOT_FOUND]

