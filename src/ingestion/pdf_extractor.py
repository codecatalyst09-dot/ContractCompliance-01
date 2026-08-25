import pymupdf as fitz
from typing import List
from src.models.schemas import PageContent, TableData

def extract_pdf(file_path: str) -> tuple[List[PageContent], str, List[TableData]]:
    """
    Extracts text and page numbers from text-based PDFs using PyMuPDF.
    Returns (pages, full_text, tables).
    """
    pages: List[PageContent] = []
    full_text_list: List[str] = []
    tables: List[TableData] = []

    doc = fitz.open(file_path)
    for page_idx, page in enumerate(doc, start=1):
        text = page.get_text() or ""
        text = text.strip()
        pages.append(PageContent(page_number=page_idx, text=text))
        if text:
            full_text_list.append(f"--- Page {page_idx} ---\n{text}")

    full_text = "\n\n".join(full_text_list)
    doc.close()
    return pages, full_text, tables
