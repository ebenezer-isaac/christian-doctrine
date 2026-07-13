"""evidence_inspect: read a stored v3.1 evidence file by question_id."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from cd_mcp.tools._common import (
    ToolInputBase,
    error_envelope,
    success_envelope,
    validate_question_id,
)

TOOL_NAME = "evidence_inspect"
EVIDENCE_DIR = Path("evidence")


class EvidenceInspectInput(ToolInputBase):
    question_id: str
    include_full_schema: bool = True


def handle(payload: EvidenceInspectInput, evidence_dir: Path | None = None) -> dict[str, Any]:
    try:
        qid = validate_question_id(payload.question_id)
    except ValueError as exc:
        return error_envelope(TOOL_NAME, "invalid_question_id", str(exc), payload.caller_context)
    path = (evidence_dir or EVIDENCE_DIR) / f"{qid}.json"
    if not path.exists():
        return error_envelope(
            TOOL_NAME, "evidence_missing", f"no evidence for {qid}", payload.caller_context
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return error_envelope(TOOL_NAME, "evidence_corrupt", str(exc), payload.caller_context)
    sources_used = list(raw.get("license_audit", {}).get("sources_used", []))
    sources_for_envelope = [
        {"source": s.get("source", "<unknown>"), "license": s.get("license", "<unknown>")}
        for s in sources_used
    ]
    result = (
        raw
        if payload.include_full_schema
        else {
            "question_id": raw.get("question_id"),
            "verdict": raw.get("verdict"),
            "lay_summary": raw.get("lay_summary"),
        }
    )
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources_for_envelope,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(name=TOOL_NAME, description="Read a v3.1 evidence file by question_id.")
    def _tool(
        question_id: str,
        include_full_schema: bool = True,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = EvidenceInspectInput(
            question_id=question_id,
            include_full_schema=include_full_schema,
            caller_context=caller_context,
        )
        return handle(payload)
