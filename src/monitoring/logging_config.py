import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

class JSONLinesHandler(logging.Handler):
    """Custom logging handler that writes structured JSON lines to a file."""
    def __init__(self, file_path: str = "logs/application.jsonl"):
        super().__init__()
        self.file_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

    def emit(self, record: logging.LogRecord):
        try:
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage()
            }
            if hasattr(record, "structured_data"):
                log_entry.update(record.structured_data)
            
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            self.handleError(record)

def get_logger(name: str = "contract_compliance") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s - %(message)s")
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        # JSON lines file handler
        json_handler = JSONLinesHandler("logs/application.jsonl")
        logger.addHandler(json_handler)
    return logger

def log_event(
    logger: logging.Logger,
    level: str,
    stage: str,
    event: str,
    run_id: str,
    agent: Optional[str] = None,
    duration_ms: Optional[float] = None,
    status: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None
):
    """Convenience helper to emit compliant structured log events."""
    data = {
        "run_id": run_id,
        "stage": stage,
        "event": event,
        "agent": agent,
        "duration_ms": duration_ms,
        "status": status,
        "error_type": error_type,
        "error_message": error_message
    }
    if extra:
        data.update(extra)
    
    # Filter out None values
    clean_data = {k: v for k, v in data.items() if v is not None}
    
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(
        f"[{stage}] {event} (run_id={run_id}, status={status or 'N/A'})",
        extra={"structured_data": clean_data}
    )
