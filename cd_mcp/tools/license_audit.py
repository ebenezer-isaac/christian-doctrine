"""license_audit: redistribution audit for an evidence file or response trace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from cd_mcp.tools._common import (
    ToolInputBase,
    error_envelope,
    success_envelope,
    validate_question_id,
    validate_uuid,
)
from ingest.license_guard import check_redistribute

TOOL_NAME = "license_audit"
EVIDENCE_DIR = Path("evidence")
TRACE_DIR = Path("tmp/response_traces")


class LicenseAuditInput(ToolInputBase):
    subject_type: Literal["evidence_file", "response_trace"]
    subject_id: str


def handle(
    payload: LicenseAuditInput,
    evidence_dir: Path | None = None,
    trace_dir: Path | None = None,
) -> dict[str, Any]:
    try:
        if payload.subject_type == "evidence_file":
            sid = validate_question_id(payload.subject_id)
            path = (evidence_dir or EVIDENCE_DIR) / f"{sid}.json"
        else:
            sid = validate_uuid(payload.subject_id)
            path = (trace_dir or TRACE_DIR) / f"{sid}.json"
    except ValueError as exc:
        return error_envelope(TOOL_NAME, "invalid_subject_id", str(exc), payload.caller_context)
    if not path.exists():
        return error_envelope(
            TOOL_NAME, "subject_missing", f"no record at {path}", payload.caller_context
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    sources = raw.get("license_audit", {}).get("sources_used", [])
    per_source: list[dict[str, Any]] = []
    for src in sources:
        check = check_redistribute(license_str=src.get("license", ""), mode="bulk")
        per_source.append(
            {
                "source": src.get("source"),
                "license": src.get("license"),
                "bulk_allowed": bool(check["allowed"]),
                "reason": check["reason"],
            }
        )
    overall_safe = all(s["bulk_allowed"] for s in per_source) if per_source else False
    result_payload: dict[str, Any] = {
        "subject_type": payload.subject_type,
        "subject_id": sid,
        "per_source": per_source,
        "bulk_redistributable": overall_safe,
    }
    return success_envelope(
        tool=TOOL_NAME,
        result=result_payload,
        sources_used=[
            {"source": s.get("source", "?"), "license": s.get("license", "?")} for s in sources
        ],
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(
        name=TOOL_NAME, description="Redistribution audit on an evidence file or response trace."
    )
    def _tool(
        subject_type: Literal["evidence_file", "response_trace"],
        subject_id: str,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = LicenseAuditInput(
            subject_type=subject_type,
            subject_id=subject_id,
            caller_context=caller_context,
        )
        return handle(payload)
