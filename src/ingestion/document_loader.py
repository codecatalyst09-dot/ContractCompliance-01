import os
import hashlib
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from src.models.schemas import (
    FileType,
    DocumentMetadata,
    PageContent,
    TableData,
    ExtractedDocument
)
from src.ingestion.pdf_extractor import extract_pdf
from src.ingestion.docx_extractor import extract_docx
from src.ingestion.document_intelligence import extract_with_document_intelligence

def compute_sha256(file_path: str) -> str:
    """Calculates SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def detect_file_type(file_name: str) -> FileType:
    ext = os.path.splitext(file_name)[1].lower()
    if ext == ".pdf":
        return FileType.PDF
    elif ext in [".docx", ".doc"]:
        return FileType.DOCX
    elif ext in [".txt", ".md"]:
        return FileType.TXT
    else:
        raise ValueError(f"Unsupported document extension: '{ext}'. Allowed: .pdf, .docx, .txt")

def extract_txt(file_path: str) -> tuple[List[PageContent], str, List[TableData]]:
    """Extracts text directly from plain text / markdown files."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read().strip()
    pages = [PageContent(page_number=1, text=content)]
    return pages, content, []

def load_and_extract_document(
    file_path: str,
    run_id: Optional[str] = None,
    use_document_intelligence: bool = False
) -> ExtractedDocument:
    """
    Main document loader & extractor abstraction.
    Scans document, computes metadata, extracts text/pages/tables, and returns ExtractedDocument.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found at path: {file_path}")

    file_name = os.path.basename(file_path)
    file_type = detect_file_type(file_name)
    file_size = os.path.getsize(file_path)
    file_hash = compute_sha256(file_path)
    current_run_id = run_id or str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    metadata = DocumentMetadata(
        run_id=current_run_id,
        file_name=file_name,
        file_path=os.path.abspath(file_path),
        file_type=file_type,
        file_size=file_size,
        file_hash=file_hash,
        ingestion_timestamp=timestamp
    )

    pages: List[PageContent] = []
    full_text: str = ""
    tables: List[TableData] = []

    if use_document_intelligence and file_type == FileType.PDF:
        try:
            pages, full_text, tables = extract_with_document_intelligence(file_path)
        except Exception as e:
            # Fallback to local PDF extraction if Document Intelligence fails or is unconfigured
            pages, full_text, tables = extract_pdf(file_path)
    elif file_type == FileType.PDF:
        pages, full_text, tables = extract_pdf(file_path)
    elif file_type == FileType.DOCX:
        pages, full_text, tables = extract_docx(file_path)
    elif file_type == FileType.TXT:
        pages, full_text, tables = extract_txt(file_path)

    return ExtractedDocument(
        document_id=file_hash[:16],
        file_name=file_name,
        metadata=metadata,
        pages=pages,
        text=full_text,
        tables=tables
    )
