import os
import pytest
from src.ingestion.document_loader import load_and_extract_document
from src.models.schemas import FileType

def test_load_sample_contract_txt():
    file_path = "documents/sample_contract.txt"
    assert os.path.exists(file_path)
    
    doc = load_and_extract_document(file_path)
    
    assert doc.file_name == "sample_contract.txt"
    assert doc.metadata.file_type == FileType.TXT
    assert len(doc.metadata.file_hash) == 64
    assert len(doc.pages) == 1
    assert len(doc.text) > 0
    assert "MASTER SERVICES AGREEMENT" in doc.text
