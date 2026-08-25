"""
FastAPI Web Application — Contract Compliance Agent Dashboard
"""

import os
import sys
import json
import uuid
import shutil
import asyncio
from pathlib import Path
from typing import List, Optional
from datetime import datetime

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.database.db import (
    init_db, create_run, update_run_from_result, mark_run_failed,
    get_all_runs, get_run, delete_run, get_stats
)
from src.workflow.compliance_workflow import ContractComplianceWorkflow
from src.monitoring.logging_config import get_logger

logger = get_logger("api")

# ── Ensure required output directories exist ──────────────────────────────────
for d in ["uploads", "outputs/compliance", "outputs/evidence", "outputs/evidence_images", "outputs/audit", "database"]:
    os.makedirs(d, exist_ok=True)

# ── Initialise SQLite DB ──────────────────────────────────────────────────────
init_db()

# ── Project paths ─────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
POLICIES_DIR = ROOT_DIR / "policies"
static_dir = Path(__file__).parent.parent / "static"

# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(title="Contract Compliance Agent", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ── WebSocket Manager ─────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, run_id: str, ws: WebSocket):
        await ws.accept()
        self.active[run_id] = ws

    def disconnect(self, run_id: str):
        self.active.pop(run_id, None)

    async def send(self, run_id: str, data: dict):
        ws = self.active.get(run_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(run_id)

manager = ConnectionManager()

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_path = static_dir / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/api/stats")
async def api_stats():
    return get_stats()


@app.get("/api/runs")
async def api_list_runs(limit: int = 200, offset: int = 0):
    return get_all_runs(limit=limit, offset=offset)


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.delete("/api/runs/{run_id}")
async def api_delete_run(run_id: str):
    deleted = delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"deleted": True, "run_id": run_id}


@app.get("/api/runs/{run_id}/report")
async def api_get_report(run_id: str):
    path = f"outputs/compliance/{run_id}_report.md"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path, media_type="text/markdown", filename=f"{run_id}_report.md")


@app.get("/api/evidence/{run_id}/{policy_id}")
async def api_get_evidence_image(run_id: str, policy_id: str):
    normalized = policy_id.replace("-", "_").replace(" ", "_").upper()
    path = f"outputs/evidence_images/{run_id}_{normalized}_evidence.jpg"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Evidence image not found")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/policies")
async def api_list_policies():
    """Return list of policy files available on the server."""
    found = []
    for d in [POLICIES_DIR, Path("policies")]:
        if d.exists() and d.is_dir():
            for f in d.glob("*.json"):
                if f.name not in found:
                    found.append(f.name)
    if not found and (POLICIES_DIR / "policies.json").exists():
        found.append("policies.json")
    return {"policy_files": sorted(found)}


@app.get("/monitor", response_class=HTMLResponse)
async def serve_monitor():
    monitor_path = static_dir / "monitor.html"
    return HTMLResponse(content=monitor_path.read_text(encoding="utf-8"))


@app.get("/api/logs")
async def api_get_logs(limit: int = 200, run_id: Optional[str] = None, level: Optional[str] = None):
    """Return structured log entries, optionally filtered by run_id and/or level."""
    from collections import deque
    log_path = "logs/application.jsonl"
    if not os.path.exists(log_path):
        return {"logs": []}
    lines: deque = deque(maxlen=max(1, limit))
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    # Filter by run_id if provided
                    if run_id and entry.get("run_id") != run_id:
                        continue
                    # Filter by level if provided
                    if level and entry.get("level", "").upper() != level.upper():
                        continue
                    lines.append(entry)
                except Exception:
                    if not run_id and not level:
                        lines.append({"message": line, "level": "INFO"})
    return {"logs": list(lines)}


@app.get("/api/runs/{run_id}/risk-breakdown")
async def api_get_risk_breakdown(run_id: str):
    """Return structured risk score calculation and details."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Load policy requirements to show "what was expected"
    policy_file = run.get("policy_file") or "policies/policies.json"
    p_path = Path(policy_file)
    if not p_path.is_file():
        if (POLICIES_DIR / p_path.name).is_file():
            p_path = POLICIES_DIR / p_path.name
        elif (ROOT_DIR / policy_file).is_file():
            p_path = ROOT_DIR / policy_file

    policies_map = {}
    if p_path.is_file():
        try:
            with open(p_path, "r", encoding="utf-8") as pf:
                p_list = json.load(pf)
                for p in p_list:
                    policies_map[p.get("policy_id")] = p
        except Exception:
            pass

    weights = {"CRITICAL": 40, "HIGH": 25, "MEDIUM": 10, "LOW": 5}
    multipliers = {"NON_COMPLIANT": 1.0, "NOT_FOUND": 1.0, "PARTIAL": 0.5, "COMPLIANT": 0.0}
    
    contributors = []
    total_score = 0.0
    
    for f in run.get("findings", []):
        status = f.get("status", "COMPLIANT")
        severity = f.get("severity", "LOW")
        weight = weights.get(severity, 5)
        multiplier = multipliers.get(status, 0.0)
        penalty = weight * multiplier
        
        formula = f"{severity} ({weight} pts) * {status.replace('_', ' ')} ({int(multiplier * 100)}%)"
        p_def = policies_map.get(f.get("policy_id"), {})
        requirement = p_def.get("requirement", "No standard requirement defined.")
        
        contributors.append({
            "policy_id": f.get("policy_id"),
            "policy_name": f.get("policy_name"),
            "status": status,
            "severity": severity,
            "penalty": penalty,
            "formula": formula,
            "expected": requirement,
            "actual_evidence": f.get("evidence") or "No direct clause reference or evidence snippet found in the contract text.",
            "status_reason": f.get("finding", "")
        })
        total_score += penalty
        
    contributors = sorted(contributors, key=lambda x: x["penalty"], reverse=True)
    capped = min(100, int(round(total_score)))
    non_compliant_count = sum(1 for c in contributors if c["penalty"] > 0)
    
    if capped == 0:
        score_explanation = "This contract is fully compliant with all checked policies. 0 risk points were accumulated."
    else:
        score_explanation = (
            f"This contract has a risk score of {capped}/100. "
            f"It accumulated a raw penalty of {total_score:.1f} points across {non_compliant_count} compliance finding(s). "
            f"Critical violations add 40 pts, High add 25 pts, Medium add 10 pts, and Low add 5 pts, multiplied by severity status."
        )
        
    return {
        "score": capped,
        "risk_level": run.get("risk_level", "LOW"),
        "score_explanation": score_explanation,
        "contributors": contributors
    }


@app.get("/api/runs/{run_id}/audit")
async def api_get_audit(run_id: str):
    """Return detailed audit trail JSON for a specific run."""
    path = f"outputs/audit/{run_id}_audit.json"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Audit trail not found")
    return FileResponse(path, media_type="application/json")


@app.post("/api/run")
async def api_submit_run(
    files: List[UploadFile] = File(...),
    policy_source: str = Form(...),        # "server" or "upload"
    policy_filename: Optional[str] = Form(None),   # for server policy
    policy_file: Optional[UploadFile] = File(None), # for uploaded policy
    concurrency: Optional[int] = Form(None),
):
    """
    Accept one or more contract documents, run the compliance workflow,
    persist results to SQLite, and return all run_ids.
    """
    # Resolve policy file path
    if policy_source == "server":
        if not policy_filename:
            raise HTTPException(status_code=400, detail="policy_filename required when policy_source=server")
        if (POLICIES_DIR / policy_filename).is_file():
            policy_path = str(POLICIES_DIR / policy_filename)
        elif Path(f"policies/{policy_filename}").is_file():
            policy_path = f"policies/{policy_filename}"
        elif (ROOT_DIR / policy_filename).is_file():
            policy_path = str(ROOT_DIR / policy_filename)
        else:
            raise HTTPException(status_code=400, detail=f"Policy file not found: {policy_filename}")
    elif policy_source == "upload":
        if not policy_file:
            raise HTTPException(status_code=400, detail="policy_file upload required when policy_source=upload")
        policy_filename = Path(policy_file.filename).name if policy_file.filename else "policy.json"
        policy_path = f"uploads/{uuid.uuid4()}_{policy_filename}"
        with open(policy_path, "wb") as f:
            shutil.copyfileobj(policy_file.file, f)
    else:
        raise HTTPException(status_code=400, detail="policy_source must be 'server' or 'upload'")

    # Save uploaded contract files to temp storage
    saved_files = []
    for uf in files:
        # Extract only the base filename to prevent errors when uploading folder structures
        filename = Path(uf.filename).name if uf.filename else "document"
        dest = f"uploads/{uuid.uuid4()}_{filename}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(uf.file, f)
        saved_files.append((dest, filename))

    # Determine concurrency
    import os as _os
    auto_concurrency = concurrency if concurrency else min(_os.cpu_count() or 4, len(saved_files))
    sem = asyncio.Semaphore(min(auto_concurrency, len(saved_files)))

    run_ids = []
    workflow = ContractComplianceWorkflow(policy_file_path=policy_path)

    async def process(file_path: str, orig_name: str):
        run_id = str(uuid.uuid4())
        run_ids.append(run_id)
        create_run(run_id, orig_name, file_path, policy_path)

        async def progress_cb(stage: str, status: str):
            await manager.send(run_id, {"run_id": run_id, "stage": stage, "status": status})

        async with sem:
            try:
                result = await workflow.execute(
                    file_path=file_path,
                    run_id=run_id,
                    progress_callback=progress_cb,
                )
                update_run_from_result(run_id, result, policy_path)
                await manager.send(run_id, {"run_id": run_id, "stage": "workflow", "status": "COMPLETED"})
            except Exception as e:
                mark_run_failed(run_id, str(e))
                await manager.send(run_id, {"run_id": run_id, "stage": "workflow", "status": "FAILED", "error": str(e)})

    # Fire all documents concurrently
    await asyncio.gather(*[process(fp, name) for fp, name in saved_files])

    return {"run_ids": run_ids, "total": len(run_ids)}


@app.websocket("/api/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()   # keep alive
    except WebSocketDisconnect:
        manager.disconnect(run_id)
