"""doctrinal_verdict: end-to-end verdict synthesis from stored evidence + cultural overlay."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from bd_mcp.tools._common import (
    ToolInputBase,
    error_envelope,
    success_envelope,
    validate_question_id,
)
from pipeline4.historical_schema import HistoricalAttestation

TOOL_NAME = "doctrinal_verdict"
EVIDENCE_DIR = Path("evidence")
HISTORICAL_DIR = Path("historical")


def _empty_historical_block() -> dict[str, Any]:
    """The historical block when no Pipeline 4 sidecar exists for a question."""
    return {
        "attestation_present": False,
        "witnesses": [],
        "summary": "",
        "license_audit": {
            "sources_used": [],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": [],
    }


def load_historical_block(
    qid: str, historical_dir: Path | None = None
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Read and validate historical/<qid>.json, mirroring the evidence read.

    Returns the diagnostic ``historical_attestation`` block plus the witness
    sources mapped into the envelope ``sources_used`` shape so the license guard
    can fold a non-redistributable witness (e.g. a DSS CC-BY-NC-4.0 source) into
    ``response_safe_to_share``. A missing sidecar yields the empty block (most
    of the 231 questions carry no attestation).
    """
    path = (historical_dir or HISTORICAL_DIR) / f"{qid}.json"
    if not path.exists():
        return _empty_historical_block(), []
    raw = json.loads(path.read_text(encoding="utf-8"))
    attestation = HistoricalAttestation.model_validate(raw)
    dumped = attestation.model_dump(mode="json", by_alias=True)
    block = {
        "attestation_present": dumped["attestation_present"],
        "witnesses": dumped["witnesses"],
        "summary": dumped["summary"],
        "license_audit": dumped["license_audit"],
        "flags": dumped["flags"],
    }
    sources = [
        {"source": src["source_slug"], "license": src["license"]}
        for src in dumped["license_audit"]["sources_used"]
    ]
    return block, sources


class DoctrinalVerdictInput(ToolInputBase):
    proposition: str = Field(min_length=1)
    denominations: list[str] | None = None
    depth: Literal["fast", "deep"] = "fast"
    progressToken: str | None = None  # noqa: N815  MCP-protocol field, camelCase required


def transform_synthesis_to_envelope(synthesis_output: dict[str, Any]) -> dict[str, Any]:
    """Pure transform: synthesis subagent output -> MCP envelope.result + license_audit."""
    lex = dict(synthesis_output.get("lexical_verdict", {}))
    affirms = lex.pop("affirms", None)
    lexical_breadth = lex.pop("lexical_breadth", None)
    lexical_directness = lex.pop("lexical_directness", None)
    variant_stability = lex.pop("variant_stability", None)
    source_files = lex.get("source_evidence_files") or []
    evidence_file_id = ""
    if source_files:
        first = source_files[0]
        evidence_file_id = Path(first).stem
    result = {
        "verdict": affirms,
        "lexical_breadth": lexical_breadth,
        "lexical_directness": lexical_directness,
        "variant_stability": variant_stability,
        "lexical_evidence": lex,
        "cultural_overlay": synthesis_output.get("cultural_overlay"),
        "variant_sensitivity": synthesis_output.get("variant_sensitivity"),
        "evidence_file_id": evidence_file_id,
    }
    license_audit = synthesis_output.get("license_audit", {})
    return {"result": result, "license_audit": license_audit}


def _classify_to_question_id(proposition: str) -> str:
    """Map proposition prose to a question_id. v1: simple keyword match against questions.json."""
    questions_path = Path("questions.json")
    if not questions_path.exists():
        return ""
    raw = json.loads(questions_path.read_text(encoding="utf-8"))
    needle = proposition.lower()
    best_qid = ""
    best_score = 0
    for q in raw.get("questions", []):
        stmt = (q.get("statement", "") or "").lower()
        score = sum(1 for word in needle.split() if word in stmt)
        if score > best_score:
            best_score = score
            best_qid = q["id"]
    return best_qid


def handle(
    payload: DoctrinalVerdictInput,
    synthesis_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    evidence_dir: Path | None = None,
    historical_dir: Path | None = None,
) -> dict[str, Any]:
    qid = _classify_to_question_id(payload.proposition)
    if not qid:
        return error_envelope(
            TOOL_NAME,
            "no_matching_question",
            "could not classify proposition",
            payload.caller_context,
        )
    try:
        qid = validate_question_id(qid)
    except ValueError as exc:
        return error_envelope(TOOL_NAME, "invalid_question_id", str(exc), payload.caller_context)
    evidence_path = (evidence_dir or EVIDENCE_DIR) / f"{qid}.json"
    if not evidence_path.exists():
        return error_envelope(
            TOOL_NAME, "evidence_missing", f"no evidence for {qid}", payload.caller_context
        )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    try:
        historical_block, historical_sources = load_historical_block(qid, historical_dir)
    except (json.JSONDecodeError, ValueError) as exc:
        return error_envelope(
            TOOL_NAME,
            "historical_corrupt",
            f"historical sidecar for {qid} failed validation: {exc}",
            payload.caller_context,
        )

    synthesis_input = {
        "question_id": qid,
        "proposition": payload.proposition,
        "depth": payload.depth,
        "denominations": payload.denominations,
        "evidence": evidence,
        "historical": historical_block,
    }
    if synthesis_fn is None:
        synthesis_output = {
            "lexical_verdict": {
                "affirms": evidence["verdict"]["affirms"],
                "lexical_breadth": evidence["verdict"]["lexical_breadth"],
                "lexical_directness": evidence["verdict"]["lexical_directness"],
                "variant_stability": evidence["verdict"]["variant_stability"],
                "source_evidence_files": [f"evidence/{qid}.json"],
            },
            "cultural_overlay": {"by_tradition": {}},
            "variant_sensitivity": evidence.get("variants", {}),
            "license_audit": evidence.get("license_audit", {}),
        }
    else:
        synthesis_output = synthesis_fn(synthesis_input)

    transformed = transform_synthesis_to_envelope(synthesis_output)
    result = transformed["result"]
    license_audit = transformed["license_audit"]

    if result["verdict"] != evidence["verdict"]["affirms"]:
        return error_envelope(
            TOOL_NAME,
            "verdict_fidelity_violation",
            "Synthesis verdict does not match stored evidence file. "
            "Re-derivation at query time is forbidden.",
            payload.caller_context,
        )

    # The historical attestation is a diagnostic block, sourced authoritatively
    # from the Pipeline 4 sidecar and never re-derived by synthesis (mirrors the
    # verdict-fidelity rule). It rides alongside the lexical verdict, never fused.
    result["historical_attestation"] = historical_block

    sources = [
        {"source": s.get("source", "?"), "license": s.get("license", "?")}
        for s in license_audit.get("sources_used", [])
    ]
    sources.extend(historical_sources)
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(
        name=TOOL_NAME, description="End-to-end doctrinal verdict with stored-evidence fidelity."
    )
    def _tool(
        proposition: str,
        denominations: list[str] | None = None,
        depth: Literal["fast", "deep"] = "fast",
        progressToken: str | None = None,  # noqa: N803
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = DoctrinalVerdictInput(
            proposition=proposition,
            denominations=denominations,
            depth=depth,
            progressToken=progressToken,
            caller_context=caller_context,
        )
        return handle(payload)
