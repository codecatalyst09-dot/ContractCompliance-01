import os
import json
import asyncio
import pytest
from src.workflow.compliance_workflow import ContractComplianceWorkflow
from src.models.schemas import DocumentType

def test_workflow_end_to_end_contract():
    async def _test():
        workflow = ContractComplianceWorkflow()
        result = await workflow.execute("documents/sample_contract.txt")

        assert result.run_id is not None
        assert result.classification.is_contract is True
        assert result.classification.document_type == DocumentType.CONTRACT
        assert result.obligations is not None
        assert len(result.obligations.obligations) > 0
        assert result.compliance is not None
        assert result.compliance.overall_status in ["PASS", "RISK", "FAIL"]
        assert result.risk is not None
        assert 0 <= result.risk.score <= 100
        assert result.evidence is not None
        assert len(result.evidence.evidence_items) > 0
        for ev_item in result.evidence.evidence_items:
            assert ev_item.image_path is not None
            assert ev_item.image_path.endswith(".jpg")
            assert os.path.exists(ev_item.image_path)
        assert len(result.recommendations) > 0


        compliance_json = f"outputs/compliance/{result.run_id}_compliance.json"
        report_md = f"outputs/compliance/{result.run_id}_report.md"
        audit_json = f"outputs/audit/{result.run_id}_audit.json"

        assert os.path.exists(compliance_json)
        assert os.path.exists(report_md)
        assert os.path.exists(audit_json)

    asyncio.run(_test())

def test_workflow_end_to_end_non_contract_skipped():
    async def _test():
        workflow = ContractComplianceWorkflow()
        result = await workflow.execute("documents/sample_non_contract.txt")

        assert result.run_id is not None
        assert result.classification.is_contract is False
        assert result.processing_metadata.get("workflow_status") == "SKIPPED"
        assert result.obligations is None

        audit_json = f"outputs/audit/{result.run_id}_audit.json"
        assert os.path.exists(audit_json)

    asyncio.run(_test())

def test_audit_trail_structure():
    async def _test():
        workflow = ContractComplianceWorkflow()
        result = await workflow.execute("documents/sample_contract.txt")

        audit_path = f"outputs/audit/{result.run_id}_audit.json"
        assert os.path.exists(audit_path)

        with open(audit_path, "r", encoding="utf-8") as f:
            audit = json.load(f)

        assert audit["run_id"] == result.run_id
        assert audit["document_hash"] is not None
        assert len(audit["document_hash"]) == 64
        assert audit["workflow_status"] == "COMPLETED"
        assert len(audit["stages_executed"]) >= 7
        assert audit["classification"] is not None
        assert audit["obligations_extracted"] > 0
        assert audit["compliance_status"] in ["PASS", "RISK", "FAIL"]
        assert len(audit["compliance_findings"]) > 0
        assert audit["risk_score"] is not None
        assert isinstance(audit["recommendations"], list)
        assert audit["errors"] == []

    asyncio.run(_test())

def test_workflow_error_audit_trail():
    async def _test():
        workflow = ContractComplianceWorkflow()
        with pytest.raises(FileNotFoundError):
            await workflow.execute("documents/non_existent_file.pdf")

    asyncio.run(_test())

def test_opentelemetry_traces():
    from src.monitoring.telemetry import get_recorded_spans, clear_recorded_spans
    async def _test():
        clear_recorded_spans()
        workflow = ContractComplianceWorkflow()
        result = await workflow.execute("documents/sample_contract.txt")

        spans = get_recorded_spans()
        assert len(spans) >= 8  # 1 workflow span + 7 stage spans

        span_names = [s.name for s in spans]
        assert "compliance_workflow_execution" in span_names
        assert "stage_ingestion" in span_names
        assert "stage_classification" in span_names
        assert "stage_obligation_extraction" in span_names
        assert "stage_policy_matching" in span_names
        assert "stage_compliance_validation" in span_names
        assert "stage_risk_scoring" in span_names
        assert "stage_evidence_generation" in span_names

        # Verify root workflow span attributes
        root_span = next(s for s in spans if s.name == "compliance_workflow_execution")
        assert root_span.attributes.get("workflow.run_id") == result.run_id
        assert root_span.attributes.get("workflow.status") == "SUCCESS"

    asyncio.run(_test())

