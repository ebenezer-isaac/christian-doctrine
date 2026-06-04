"""historical_inspect: read a stored Pipeline 4 historical-attestation sidecar.

Mirrors evidence_inspect: same question-id regex defense, same envelope, but
reads ``historical/<question_id>.json`` and validates it against the
HistoricalAttestation schema before returning. Diagnostic only; the sidecar
never adjudicates the lexical verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from bd_mcp.tools._common import (
    ToolInputBase,
    error_envelope,
    success_envelope,
    validate_question_id,
)
from pipeline4.historical_schema import HistoricalAttestation

TOOL_NAME = "historical_inspect"
HISTORICAL_DIR = Path("historical")


class HistoricalInspectInput(ToolInputBase):
    question_id: str
    include_full_schema: bool = True


def handle(payload: HistoricalInspectInput, historical_dir: Path | None = None) -> dict[str, Any]:
    try:
        qid = validate_question_id(payload.question_id)
    except ValueError as exc:
        return error_envelope(TOOL_NAME, "invalid_question_id", str(exc), payload.caller_context)
    path = (historical_dir or HISTORICAL_DIR) / f"{qid}.json"
    if not path.exists():
        return error_envelope(
            TOOL_NAME,
            "historical_missing",
            f"no historical sidecar for {qid}",
            payload.caller_context,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return error_envelope(TOOL_NAME, "historical_corrupt", str(exc), payload.caller_context)
    try:
        attestation = HistoricalAttestation.model_validate(raw)
    except ValueError as exc:
        return error_envelope(TOOL_NAME, "historical_corrupt", str(exc), payload.caller_context)

    dumped = attestation.model_dump(mode="json", by_alias=True)
    sources_for_envelope = [
        {"source": s.get("source_slug", "<unknown>"), "license": s.get("license", "<unknown>")}
        for s in dumped.get("license_audit", {}).get("sources_used", [])
    ]
    result = (
        dumped
        if payload.include_full_schema
        else {
            "question_id": dumped.get("question_id"),
            "attestation_present": dumped.get("attestation_present"),
            "summary": dumped.get("summary"),
            "flags": dumped.get("flags"),
        }
    )
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources_for_envelope,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(
        name=TOOL_NAME,
        description="Read a Pipeline 4 historical-attestation sidecar by question_id.",
    )
    def _tool(
        question_id: str,
        include_full_schema: bool = True,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = HistoricalInspectInput(
            question_id=question_id,
            include_full_schema=include_full_schema,
            caller_context=caller_context,
        )
        return handle(payload)
