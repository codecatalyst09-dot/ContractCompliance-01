# ⚖️ Contract Compliance Agent (MAF)

An enterprise-grade, end-to-end **Contract Compliance & Risk Analysis System** built using the **Microsoft Agent Framework (MAF)** for Python, Azure AI Foundry, and FastAPI.

---

## 🌟 Key Features

- **Multi-Agent Orchestration**: Specialized agents for Classification, Obligation Extraction, Policy Matching, Compliance Validation, and Evidence Generation.
- **Full Folder & Batch Ingestion**: Upload single files or drag-and-drop entire folders with nested subdirectories (PDF, DOCX, TXT supported).
- **High-Resolution Visual Evidence Cards**: Generates full-width, crisp PDF page snippet extracts with highlighted clauses, document metadata, and status badges.
- **Deterministic Risk Scoring**: Transparent, auditable compliance scoring (0–100) with severity levels (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- **Interactive Web Dashboard**: Modern UI with live WebSocket progress tracking, KPI cards, visual evidence lightbox, and report downloads.
- **Real-Time Monitoring & Telemetry**:
  - Live structured event streaming (`logs/application.jsonl`) with search & level filters.
  - OpenTelemetry distributed tracing and metrics (`workflow_duration_ms`, `stage_duration_ms`).
  - Azure Monitor / Application Insights integration.
- **Complete Audit Trail**: Automated generation of immutable audit JSON records and Markdown compliance reports.

---

## 🏗️ Architecture & Workflow

```
                        INBOUND DOCUMENTS
                     (Single Files / Folders)
                                │
                                ▼
                    STAGE 1: DOCUMENT INGESTION
          (PyMuPDF / python-docx / Azure Doc Intelligence)
                                │
                                ▼
                   STAGE 2: CLASSIFICATION AGENT
        ┌───────────────────────┴───────────────────────┐
   [Contract]                                     [Non-Contract]
        │                                               │
        ▼                                               ▼
STAGE 3: OBLIGATION EXTRACTION AGENT              SKIPPED (End)
        │
        ▼
STAGE 4: POLICY & CLAUSE MATCHING AGENT
        │
        ▼
STAGE 5: COMPLIANCE VALIDATION AGENT
        │
        ▼
STAGE 6: DETERMINISTIC RISK SCORING ENGINE
        │
        ▼
STAGE 7: EVIDENCE GENERATION AGENT
  (Full-Width PDF Snippet Highlighting & Card Rendering)
        │
        ▼
OUTPUTS & MONITORING
  ├── Compliance JSON (`outputs/compliance/`)
  ├── Executive Markdown Report (`outputs/compliance/`)
  ├── Evidence Pack & Visual Cards (`outputs/evidence/`, `outputs/evidence_images/`)
  ├── Audit Trail (`outputs/audit/`)
  ├── Application Event Stream (`logs/application.jsonl`)
  └── OpenTelemetry Spans & Azure Application Insights
```

---

## 📂 Project Structure

```
Contract Compliance/
├── documents/                # Sample contract documents
├── policies/                 # Policy definition files (policies.json)
├── outputs/                  # Generated analysis outputs
│   ├── compliance/           # Compliance JSON & Markdown reports
│   ├── evidence/             # Evidence packs
│   ├── evidence_images/      # Rendered visual evidence snippet cards
│   └── audit/                # Full audit trail records
├── logs/                     # Application logs (application.jsonl)
├── src/
│   ├── agents/               # MAF Specialized Agents
│   │   ├── classification_agent.py
│   │   ├── obligation_agent.py
│   │   ├── policy_agent.py
│   │   ├── validation_agent.py
│   │   ├── evidence_agent.py
│   │   └── client_factory.py
│   ├── api/                  # FastAPI web server & WebSocket manager
│   │   └── app.py
│   ├── database/             # SQLite run database
│   │   └── db.py
│   ├── ingestion/            # Document loaders (PDF, DOCX, TXT)
│   │   ├── document_loader.py
│   │   ├── pdf_extractor.py
│   │   ├── docx_extractor.py
│   │   └── document_intelligence.py
│   ├── models/               # Pydantic schemas & state models
│   │   └── schemas.py
│   ├── monitoring/           # OpenTelemetry tracing & JSON logging
│   │   ├── logging_config.py
│   │   └── telemetry.py
│   ├── scoring/              # Deterministic risk engine
│   │   └── risk_scoring.py
│   ├── services/             # Visualizer, report & policy services
│   │   ├── evidence_visualizer.py
│   │   ├── report_generator.py
│   │   └── policy_service.py
│   ├── static/               # Web Dashboard frontend (HTML/CSS/JS)
│   │   └── index.html
│   ├── workflow/             # Workflow orchestrator
│   │   └── compliance_workflow.py
│   ├── config.py             # Environment configuration
│   └── main.py               # CLI entrypoint
├── tests/                    # Unit and integration test suites
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore configuration
└── requirements.txt          # Python dependencies
```

---

## 🚀 Quick Start

### 1. Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/codecatalyst09-dot/ContractCompliance.git
cd ContractCompliance
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy `.env.example` to `.env` and provide your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```ini
# --- Azure AI Foundry (Required) ---
FOUNDRY_OPENAI_BASE_URL=https://<your-resource>.services.ai.azure.com/openai/v1
FOUNDRY_API_KEY=your_api_key_here
FOUNDRY_MODEL=gpt-4.1-mini

# --- Azure AI Document Intelligence (Optional) ---
DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
DOCUMENT_INTELLIGENCE_API_KEY=your_doc_intel_key_here

# --- Azure Application Insights (Optional) ---
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...
```

---

## 🖥️ Running the Application

### Option A: Interactive Web Dashboard (Recommended)

Start the web server:

```bash
uvicorn src.api.app:app --reload --port 8000
```
or
```bash
python -m uvicorn src.api.app:app --reload --port 8000
```

Open your browser at **[http://localhost:8000](http://localhost:8000)**.

#### Dashboard Capabilities:
- **Batch & Folder Upload**: Click "Choose Entire Folder" or drag-and-drop a folder to process multiple files in parallel.
- **Policy Selection**: Use server-defined policies or upload custom policy JSONs.
- **Live Workflow Progress**: Watch real-time stage transitions via WebSockets.
- **Evidence Lightbox**: Inspect highlighted clause snippets from contracts.
- **System Monitoring**: View live telemetry, execution times, and filtered log records.

---

### Option B: Command Line Interface (CLI)

#### Process a Single Contract:
```bash
python -m src.main --file documents/sample_contract.txt --policy-file policies/policies.json
```

#### Process an Entire Folder (with Parallel Workers):
```bash
python -m src.main --folder documents/ --policy-file policies/policies.json --concurrency 4
```

#### CLI Flags:
- `--file <path>`: Single file to process.
- `--folder <path>`: Directory of documents to process in batch.
- `--policy-file <path>`: Path to policy JSON file.
- `--concurrency <N>`: Number of concurrent workers (default: auto).
- `--verbose`: Output verbose clause-level evaluations to terminal.
- `--use-doc-intel`: Enable Azure AI Document Intelligence for OCR/scanned PDFs.

---

## 🧪 Testing

Run all unit and integration tests:

```bash
pytest
```

---

## 📊 Monitoring & Observability

- **Structured Logs**: Continuous JSONL logging in `logs/application.jsonl`.
- **OpenTelemetry Metrics**:
  - `compliance_workflow_runs_total`: Total workflow executions.
  - `compliance_workflow_duration_ms`: End-to-end execution latency.
  - `compliance_stage_duration_ms`: Per-agent stage latencies.
- **Azure Application Insights**: Native exporter support for production monitoring.

---

## 📄 License

This project is distributed under the MIT License.
