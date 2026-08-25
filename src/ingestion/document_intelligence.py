from typing import List, Optional, Dict, Any
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from src.config import config
from src.models.schemas import PageContent, TableData

def extract_with_document_intelligence(file_path: str) -> tuple[List[PageContent], str, List[TableData]]:
    """
    Extracts text, pages, and tables using Azure AI Document Intelligence.
    Requires DOCUMENT_INTELLIGENCE_ENDPOINT and DOCUMENT_INTELLIGENCE_API_KEY.
    """
    if not config.document_intelligence_endpoint or not config.document_intelligence_api_key:
        raise ValueError("Azure AI Document Intelligence endpoint or API key is not configured.")

    client = DocumentIntelligenceClient(
        endpoint=config.document_intelligence_endpoint,
        credential=AzureKeyCredential(config.document_intelligence_api_key)
    )

    with open(file_path, "rb") as f:
        poller = client.begin_analyze_document(
            model_id="prebuilt-layout",
            analyze_request=f,
            content_type="application/octet-stream"
        )
    result = poller.result()

    pages: List[PageContent] = []
    tables: List[TableData] = []
    full_text_list: List[str] = []

    if result.pages:
        for page in result.pages:
            page_text = "\n".join([line.content for line in page.lines]) if page.lines else ""
            pages.append(PageContent(page_number=page.page_number, text=page_text))
            if page_text:
                full_text_list.append(f"--- Page {page.page_number} ---\n{page_text}")

    full_text = "\n\n".join(full_text_list) if full_text_list else (result.content or "")

    if result.tables:
        for table in result.tables:
            page_num = table.bounding_regions[0].page_number if table.bounding_regions else 1
            matrix: Dict[int, Dict[int, str]] = {}
            max_r, max_c = 0, 0
            for cell in table.cells:
                r, c = cell.row_index, cell.column_index
                matrix.setdefault(r, {})[c] = cell.content or ""
                max_r = max(max_r, r)
                max_c = max(max_c, c)
            
            headers: List[str] = [matrix.get(0, {}).get(c, "") for c in range(max_c + 1)]
            rows_data: List[List[str]] = []
            for r in range(1, max_r + 1):
                rows_data.append([matrix.get(r, {}).get(c, "") for c in range(max_c + 1)])
            
            tables.append(TableData(page_number=page_num, headers=headers, rows=rows_data))

    return pages, full_text, tables
