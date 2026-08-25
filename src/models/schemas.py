from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# File & Ingestion Models
class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"

class DocumentMetadata(BaseModel):
    run_id: str
    file_name: str
    file_path: str
    file_type: FileType
    file_size: int
    file_hash: str  # SHA-256
    ingestion_timestamp: str

class PageContent(BaseModel):
    page_number: int
    text: str

class TableData(BaseModel):
    page_number: Optional[int] = None
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)

class ExtractedDocument(BaseModel):
    document_id: str
    file_name: str
    metadata: DocumentMetadata
    pages: List[PageContent] = Field(default_factory=list)
    text: str
    tables: List[TableData] = Field(default_factory=list)

# Classification Models
class DocumentType(str, Enum):
    CONTRACT = "Contract"
    PURCHASE_ORDER = "Purchase Order"
    INVOICE = "Invoice"
    POLICY = "Policy"
    OTHER = "Other"

class ClassificationResult(BaseModel):
    document_type: DocumentType
    is_contract: bool
    confidence: float
    reasoning: str
    is_confident: bool = True
    needs_review: bool = False
    status: str = "CONFIDENT"

# Obligation Models
class Obligation(BaseModel):
    obligation_id: str
    description: str
    responsible_party: Optional[str] = None
    clause_reference: Optional[str] = None
    due_date: Optional[str] = None
    sla: Optional[str] = None
    penalty: Optional[str] = None
    conditions: Optional[str] = None
    relevant_evidence: Optional[str] = None
    is_explicit: bool = True

class ObligationResult(BaseModel):
    obligations: List[Obligation] = Field(default_factory=list)
    summary: str = ""
    extraction_status: str = "SUCCESS"  # SUCCESS, FAILED, PARTIAL
    is_success: bool = True
    error_message: Optional[str] = None

# Policy & Clause Matching Models
class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    PARTIAL = "PARTIAL"
    NOT_FOUND = "NOT_FOUND"

class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class ClauseFinding(BaseModel):
    policy_id: str
    policy_name: str
    clause_reference: Optional[str] = None
    status: ComplianceStatus
    finding: str
    severity: Severity
    evidence: Optional[str] = None
    validation_status: str = "VERIFIED"  # VERIFIED, CORRECTED, FLAGGED, UNVERIFIED_EVIDENCE
    validation_notes: Optional[str] = None

class ComplianceResult(BaseModel):
    overall_status: str  # PASS, RISK, FAIL
    findings: List[ClauseFinding] = Field(default_factory=list)

# Risk Scoring Model
class RiskScore(BaseModel):
    score: int  # 0 to 100
    risk_level: Severity  # LOW, MEDIUM, HIGH, CRITICAL
    breakdown: Dict[str, Any] = Field(default_factory=dict)

# Evidence Models
class EvidenceItem(BaseModel):
    policy_id: str
    clause_reference: Optional[str] = None
    evidence: str
    source: str
    page_number: Optional[int] = None
    image_path: Optional[str] = None

class EvidencePack(BaseModel):
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


# Final Result Model
class FinalComplianceResult(BaseModel):
    run_id: str
    document: ExtractedDocument
    classification: ClassificationResult
    obligations: Optional[ObligationResult] = None
    compliance: Optional[ComplianceResult] = None
    risk: Optional[RiskScore] = None
    recommendations: List[str] = Field(default_factory=list)
    evidence: Optional[EvidencePack] = None
    processing_metadata: Dict[str, Any] = Field(default_factory=dict)
