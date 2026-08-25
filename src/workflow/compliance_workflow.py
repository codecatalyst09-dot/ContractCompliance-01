import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable, Awaitable
from pydantic import BaseModel, Field

from src.models.schemas import (
    ExtractedDocument,
    ClassificationResult,
    ObligationResult,
    ClauseFinding,
    ComplianceResult,
    RiskScore,
    EvidencePack,
    FinalComplianceResult
)
from src.ingestion.document_loader import load_and_extract_document
from src.agents.classification_agent import ClassificationAgent
from src.agents.obligation_agent import ObligationExtractionAgent
from src.agents.policy_agent import PolicyClauseMatchingAgent
from src.agents.validation_agent import ComplianceValidationAgent
from src.agents.evidence_agent import EvidenceGenerationAgent
from src.agents.risky_terms_agent import RiskyTermsAgent
from src.services.policy_service import PolicyService, Policy
from src.scoring.risk_scoring import calculate_risk_score
from src.services.template_checker import evaluate_template_policy
from src.services.report_generator import (
    save_compliance_json,
    save_evidence_json,
    save_audit_json,
    generate_markdown_report
)
from src.monitoring.logging_config import get_logger, log_event

logger = get_logger("compliance_workflow")

class WorkflowStageExecution(BaseModel):
    stage_name: str
    agent_name: Optional[str] = None
    start_time: str
    end_time: str
    duration_ms: float
    status: str
    error: Optional[str] = None

class ComplianceWorkflowState(BaseModel):
    run_id: str
    file_path: str
    status: str = "INITIALIZED"  # INITIALIZED, RUNNING, COMPLETED, SKIPPED, FAILED
    start_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: Optional[str] = None
    document: Optional[ExtractedDocument] = None
    classification: Optional[ClassificationResult] = None
    obligations: Optional[ObligationResult] = None
    initial_findings: List[ClauseFinding] = Field(default_factory=list)
    compliance_result: Optional[ComplianceResult] = None
    risk_score: Optional[RiskScore] = None
    evidence_pack: Optional[EvidencePack] = None
    stage_executions: List[WorkflowStageExecution] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)

from src.monitoring.telemetry import (
    trace_workflow_span,
    trace_stage_span,
    risk_score_histogram
)

class ContractComplianceWorkflow:
    def __init__(self, policy_file_path: str = "policies/policies.json"):
        self.policy_service = PolicyService(policy_file_path)
        self.classification_agent = ClassificationAgent()
        self.obligation_agent = ObligationExtractionAgent()
        self.policy_agent = PolicyClauseMatchingAgent()
        self.risky_terms_agent = RiskyTermsAgent()
        self.validation_agent = ComplianceValidationAgent()
        self.evidence_agent = EvidenceGenerationAgent()

    async def execute(
        self,
        file_path: str,
        run_id: Optional[str] = None,
        use_document_intelligence: bool = False,
        progress_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
    ) -> FinalComplianceResult:
        current_run_id = run_id or str(uuid.uuid4())
        state = ComplianceWorkflowState(run_id=current_run_id, file_path=file_path)

        async def _notify(stage: str, status: str):
            if progress_callback:
                await progress_callback(stage, status)

        log_event(logger, "INFO", "workflow", "workflow_started", current_run_id, extra={"file_path": file_path})
        await _notify("workflow", "STARTED")

        with trace_workflow_span(current_run_id, file_path):
            try:
                # Stage 1: Document Ingestion & Extraction
                await _notify("ingestion", "RUNNING")
                state.document = await self._run_stage(
                    state, "ingestion", "DocumentLoader",
                    lambda: load_and_extract_document(
                        file_path,
                        run_id=current_run_id,
                        use_document_intelligence=use_document_intelligence
                    )
                )
                await _notify("ingestion", "DONE")

                # Stage 2: Classification
                await _notify("classification", "RUNNING")
                state.classification = await self._run_stage(
                    state, "classification", "ClassificationAgent",
                    lambda: self.classification_agent.classify(state.document)
                )
                await _notify("classification", "DONE")

                # Check if document classification has low confidence / needs review
                if state.classification.needs_review or not state.classification.is_confident:
                    log_event(
                        logger, "WARNING", "classification", "classification_low_confidence", current_run_id,
                        agent="ClassificationAgent",
                        extra={
                            "confidence": state.classification.confidence,
                            "document_type": state.classification.document_type.value,
                            "reasoning": state.classification.reasoning
                        }
                    )

                # Check if document is a contract
                if not state.classification.is_contract:
                    state.status = "SKIPPED"
                    state.end_time = datetime.now(timezone.utc).isoformat()
                    log_event(logger, "INFO", "classification", "document_skipped_non_contract", current_run_id,
                              agent="ClassificationAgent", status="SKIPPED")

                    final_res = FinalComplianceResult(
                        run_id=current_run_id,
                        document=state.document,
                        classification=state.classification,
                        processing_metadata={
                            "workflow_status": "SKIPPED",
                            "stages_executed": [s.stage_name for s in state.stage_executions],
                            "classification_confidence": state.classification.confidence,
                            "classification_status": state.classification.status,
                            "classification_needs_review": state.classification.needs_review,
                            "reason": f"Document classified as {state.classification.document_type.value}, not a contract."
                        }
                    )
                    self._persist_artifacts(final_res, state)
                    return final_res

                # Stage 3: Obligation Extraction
                await _notify("obligation_extraction", "RUNNING")
                state.obligations = await self._run_stage(
                    state, "obligation_extraction", "ObligationExtractionAgent",
                    lambda: self.obligation_agent.extract_obligations(state.document)
                )
                if state.obligations and not state.obligations.is_success:
                    err_msg = state.obligations.error_message or "Obligation extraction failed"
                    log_event(logger, "ERROR", "obligation_extraction", "obligation_extraction_failed",
                              current_run_id, agent="ObligationExtractionAgent",
                              status="FAILED", error_message=err_msg)
                    state.errors.append({
                        "stage": "obligation_extraction",
                        "agent": "ObligationExtractionAgent",
                        "error": err_msg
                    })
                await _notify("obligation_extraction", "DONE")

                # Stage 4: Three parallel checks — template, mandatory clauses, risky terms
                policies = self.policy_service.get_all_policies()
                await _notify("template_check", "RUNNING")
                await _notify("policy_matching", "RUNNING")
                await _notify("risky_terms", "RUNNING")

                template_finding, policy_findings, risky_findings = await asyncio.gather(
                    self._run_stage(
                        state, "template_check", "TemplateChecker",
                        lambda: evaluate_template_policy(state.document, policies)
                    ),
                    self._run_stage(
                        state, "policy_matching", "PolicyClauseMatchingAgent",
                        lambda: self.policy_agent.match_policies(state.document, state.obligations, policies)
                    ),
                    self._run_stage(
                        state, "risky_terms", "RiskyTermsAgent",
                        lambda: self.risky_terms_agent.detect_risky_terms(state.document, state.obligations)
                    ),
                )
                await _notify("template_check", "DONE")
                await _notify("policy_matching", "DONE")
                await _notify("risky_terms", "DONE")

                state.initial_findings = self._merge_parallel_findings(
                    policy_findings or [],
                    template_finding,
                    risky_findings or [],
                )

                # Stage 5: Compliance Validation
                await _notify("compliance_validation", "RUNNING")
                state.compliance_result = await self._run_stage(
                    state, "compliance_validation", "ComplianceValidationAgent",
                    lambda: self.validation_agent.validate(state.document, state.obligations, state.initial_findings, policies)
                )
                await _notify("compliance_validation", "DONE")

                # Keep deterministic template result if the LLM validation overwrote it
                if template_finding and state.compliance_result:
                    state.compliance_result.findings = self._merge_parallel_findings(
                        state.compliance_result.findings,
                        template_finding,
                        [],
                    )
                    state.compliance_result.overall_status = self.validation_agent.calculate_overall_status(
                        state.compliance_result.findings
                    )

                # Stage 6: Risk Scoring (Deterministic)
                await _notify("risk_scoring", "RUNNING")
                state.risk_score = await self._run_stage(
                    state, "risk_scoring", "DeterministicRiskEngine",
                    lambda: calculate_risk_score(state.compliance_result.findings)
                )
                await _notify("risk_scoring", "DONE")
                if state.risk_score:
                    risk_score_histogram.record(state.risk_score.score, {"risk_level": state.risk_score.risk_level.value})

                # Stage 7: Evidence Generation
                await _notify("evidence_generation", "RUNNING")
                state.evidence_pack = await self._run_stage(
                    state, "evidence_generation", "EvidenceGenerationAgent",
                    lambda: self.evidence_agent.generate_evidence(
                        state.document,
                        state.compliance_result.findings,
                        state.risk_score,
                        policies
                    )
                )
                await _notify("evidence_generation", "DONE")

                state.status = "COMPLETED"
                state.end_time = datetime.now(timezone.utc).isoformat()

                final_res = FinalComplianceResult(
                    run_id=current_run_id,
                    document=state.document,
                    classification=state.classification,
                    obligations=state.obligations,
                    compliance=state.compliance_result,
                    risk=state.risk_score,
                    recommendations=state.evidence_pack.recommendations if state.evidence_pack else [],
                    evidence=state.evidence_pack,
                    processing_metadata={
                        "workflow_status": "COMPLETED",
                        "stages_executed": [s.stage_name for s in state.stage_executions],
                        "total_stages": len(state.stage_executions),
                        "start_time": state.start_time,
                        "end_time": state.end_time
                    }
                )

                self._persist_artifacts(final_res, state)
                log_event(logger, "INFO", "workflow", "workflow_completed", current_run_id, status="COMPLETED")
                return final_res

            except Exception as e:
                state.status = "FAILED"
                state.end_time = datetime.now(timezone.utc).isoformat()
                err_dict = {"stage": "workflow", "error_type": type(e).__name__, "message": str(e)}
                state.errors.append(err_dict)
                log_event(logger, "ERROR", "workflow", "workflow_failed", current_run_id,
                          status="FAILED", error_type=type(e).__name__, error_message=str(e))
                
                # Save audit trail for failed run
                self._save_audit_record(state)
                raise

    def _merge_parallel_findings(self, *finding_lists: Any) -> List[ClauseFinding]:
        merged = []
        for fl in finding_lists:
            if not fl:
                continue
            if isinstance(fl, list):
                merged.extend(fl)
            else:
                merged.append(fl)
        return merged

    async def _run_stage(self, state: ComplianceWorkflowState, stage_name: str, agent_name: str, fn):
        t0 = time.time()
        start_ts = datetime.now(timezone.utc).isoformat()
        with trace_stage_span(stage_name, agent_name, state.run_id):
            try:
                if callable(fn):
                    import inspect
                    if inspect.iscoroutinefunction(fn) or inspect.iscoroutine(fn):
                        result = await fn()
                    else:
                        res = fn()
                        if inspect.isawaitable(res):
                            result = await res
                        else:
                            result = res
                else:
                    result = fn

                duration_ms = (time.time() - t0) * 1000
                end_ts = datetime.now(timezone.utc).isoformat()

                state.stage_executions.append(WorkflowStageExecution(
                    stage_name=stage_name,
                    agent_name=agent_name,
                    start_time=start_ts,
                    end_time=end_ts,
                    duration_ms=duration_ms,
                    status="SUCCESS"
                ))

                log_event(logger, "INFO", stage_name, f"{stage_name}_completed", state.run_id,
                          agent=agent_name, duration_ms=duration_ms, status="SUCCESS")
                return result

            except Exception as e:
                duration_ms = (time.time() - t0) * 1000
                end_ts = datetime.now(timezone.utc).isoformat()
                state.stage_executions.append(WorkflowStageExecution(
                    stage_name=stage_name,
                    agent_name=agent_name,
                    start_time=start_ts,
                    end_time=end_ts,
                    duration_ms=duration_ms,
                    status="FAILED",
                    error=str(e)
                ))
                state.errors.append({"stage": stage_name, "agent": agent_name, "error": str(e)})
                log_event(logger, "ERROR", stage_name, f"{stage_name}_failed", state.run_id,
                          agent=agent_name, duration_ms=duration_ms, status="FAILED",
                          error_type=type(e).__name__, error_message=str(e))
                raise


    def _persist_artifacts(self, result: FinalComplianceResult, state: ComplianceWorkflowState):
        save_compliance_json(result)
        save_evidence_json(result)
        generate_markdown_report(result)
        self._save_audit_record(state)

    def _save_audit_record(self, state: ComplianceWorkflowState):
        audit_record = {
            "run_id": state.run_id,
            "document_name": state.document.file_name if state.document else state.file_path,
            "document_hash": state.document.metadata.file_hash if state.document else None,
            "start_time": state.start_time,
            "end_time": state.end_time,
            "workflow_status": state.status,
            "stages_executed": [s.model_dump() for s in state.stage_executions],
            "classification": state.classification.model_dump() if state.classification else None,
            "obligations_extracted": len(state.obligations.obligations) if state.obligations else 0,
            "compliance_status": state.compliance_result.overall_status if state.compliance_result else None,
            "compliance_findings": [f.model_dump() for f in state.compliance_result.findings] if state.compliance_result else [],
            "risk_score": state.risk_score.model_dump() if state.risk_score else None,
            "evidence_generated": len(state.evidence_pack.evidence_items) if state.evidence_pack else 0,
            "recommendations": state.evidence_pack.recommendations if state.evidence_pack else [],
            "errors": state.errors
        }
        save_audit_json(audit_record)

