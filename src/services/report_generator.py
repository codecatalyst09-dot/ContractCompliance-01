import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.models.schemas import FinalComplianceResult

def save_compliance_json(result: FinalComplianceResult, output_dir: str = "outputs/compliance") -> str:
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"{result.run_id}_compliance.json")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2))
    return file_path

def save_evidence_json(result: FinalComplianceResult, output_dir: str = "outputs/evidence") -> Optional[str]:
    if not result.evidence:
        return None
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"{result.run_id}_evidence.json")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(result.evidence.model_dump_json(indent=2))
    return file_path

def save_audit_json(audit_record: Dict[str, Any], output_dir: str = "outputs/audit") -> str:
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"{audit_record['run_id']}_audit.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(audit_record, f, indent=2)
    return file_path

def generate_markdown_report(result: FinalComplianceResult, output_dir: str = "outputs/compliance") -> str:
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"{result.run_id}_report.md")

    doc = result.document
    meta = doc.metadata
    cls = result.classification
    risk = result.risk
    comp = result.compliance
    obl = result.obligations
    ev = result.evidence

    md = []
    md.append(f"# Contract Compliance Report\n")
    md.append(f"**Run ID:** `{result.run_id}`  ")
    md.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  \n")

    md.append(f"## Document Information\n")
    md.append(f"- **File Name:** `{meta.file_name}`")
    md.append(f"- **Document Type:** {cls.document_type.value}")
    md.append(f"- **SHA-256 Hash:** `{meta.file_hash}`")
    md.append(f"- **File Size:** {meta.file_size:,} bytes")
    md.append(f"- **Pages:** {len(doc.pages)}\n")

    md.append(f"## Classification Summary\n")
    md.append(f"- **Is Contract:** {'✅ Yes' if cls.is_contract else '❌ No'}")
    md.append(f"- **Confidence:** {cls.confidence * 100:.1f}%")
    md.append(f"- **Reasoning:** {cls.reasoning}\n")

    if not cls.is_contract:
        md.append(f"> [!NOTE]\n> Compliance evaluation was **SKIPPED** because this document is not classified as a contract.\n")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md))
        return file_path

    md.append(f"## Executive Summary & Risk Assessment\n")
    status_icon = "🟢" if comp and comp.overall_status == "PASS" else ("🟡" if comp and comp.overall_status == "RISK" else "🔴")
    md.append(f"- **Overall Compliance Status:** {status_icon} **{comp.overall_status if comp else 'UNKNOWN'}**")
    if risk:
        md.append(f"- **Risk Score:** **{risk.score} / 100** ({risk.risk_level.value} Risk)")
        md.append(f"- **Findings Breakdown:** {risk.breakdown.get('counts', {})}\n")

    md.append(f"## Clause-Level Policy Findings\n")
    md.append("| Policy ID | Policy Name | Clause | Status | Severity | Finding & Evidence |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    if comp and comp.findings:
        for f in comp.findings:
            st_icon = "✅" if f.status.value == "COMPLIANT" else ("⚠️" if f.status.value == "PARTIAL" else "❌")
            evidence_str = f"<br>_Evidence:_ \"{f.evidence}\"" if f.evidence else ""
            clause_str = f.clause_reference or "N/A"
            md.append(f"| `{f.policy_id}` | {f.policy_name} | {clause_str} | {st_icon} {f.status.value} | `{f.severity.value}` | {f.finding}{evidence_str} |")
    else:
        md.append("| - | No findings recorded | - | - | - | - |")
    md.append("")

    if obl and obl.obligations:
        md.append(f"## Extracted Obligations ({len(obl.obligations)})\n")
        for o in obl.obligations:
            due_str = f" | Due: {o.due_date}" if o.due_date else ""
            clause_ref = f"[{o.clause_reference}] " if o.clause_reference else ""
            md.append(f"- **{o.obligation_id}** ({o.responsible_party or 'Party unspecified'}{due_str}): {clause_ref}{o.description}")
            if o.relevant_evidence:
                md.append(f"  > \"{o.relevant_evidence}\"")
        md.append("")

    if ev and ev.evidence_items:
        md.append(f"## Visual Evidence Photo Snips (JPG)\n")
        md.append("| Policy ID | Clause | Evidence Text | JPG Image Artifact |")
        md.append("| :--- | :--- | :--- | :--- |")
        for item in ev.evidence_items:
            clause_str = item.clause_reference or "N/A"
            snippet = item.evidence[:80] + ("..." if len(item.evidence) > 80 else "")
            img_rel = item.image_path or "N/A"
            md.append(f"| `{item.policy_id}` | {clause_str} | \"{snippet}\" | `{img_rel}` |")
        md.append("")

    if ev and ev.recommendations:
        md.append(f"## Recommendations\n")
        for idx, rec in enumerate(ev.recommendations, start=1):
            md.append(f"{idx}. {rec}")
        md.append("")

    md.append(f"## Audit Information\n")
    md.append(f"- **Ingestion Timestamp:** `{meta.ingestion_timestamp}`")
    md.append(f"- **Processing Run ID:** `{result.run_id}`")
    md.append(f"- **Processing Metadata:** `{json.dumps(result.processing_metadata)}`\n")


    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    return file_path
