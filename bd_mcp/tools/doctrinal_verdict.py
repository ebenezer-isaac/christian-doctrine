"""doctrinal_verdict: return the three diagnostic blocks for a doctrinal proposition.

The tool resolves a proposition to a stored question, then returns three blocks
side by side, never fused:

  1. lexical verdict   - authoritative, read verbatim from evidence/<id>.json (Pipeline 2)
  2. cultural overlay   - diagnostic, retrieved live from the cultural store
  3. historical attestation - diagnostic, read from historical/<id>.json (Pipeline 4)

The server does no synthesis of its own: it assembles structured data and the
calling model reasons over it. Because the verdict is read straight from the
stored evidence file, it cannot drift; there is no query-time re-derivation.

The query-time air-gap holds: the lexical block comes only from the evidence
file, and the cultural and historical blocks ride alongside as separate blocks
with separate license stacks. A non-redistributable source in any block folds
into the envelope license audit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from bd_mcp.runtime import cultural_chunks as retrieve_chunks
from bd_mcp.tools._common import (
    CallerContext,
    ToolInputBase,
    error_envelope,
    success_envelope,
    validate_question_id,
)
from bd_mcp.tools.cultural_overlay import build_cultural_overlay
from pipeline4.historical_schema import HistoricalAttestation

TOOL_NAME = "doctrinal_verdict"
EVIDENCE_DIR = Path("evidence")
HISTORICAL_DIR = Path("historical")


class DoctrinalVerdictInput(ToolInputBase):
    proposition: str = Field(min_length=1)
    denominations: list[str] | None = None
    depth: Literal["fast", "deep"] = "fast"
    progressToken: str | None = None  # noqa: N815  MCP-protocol field, camelCase required


# ---------------------------------------------------------------------------
# Historical block (Pipeline 4 sidecar)
# ---------------------------------------------------------------------------


def _empty_historical_block() -> dict[str, Any]:
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
    """Read and validate historical/<qid>.json. Returns (block, witness sources).

    The witness sources are mapped into the envelope ``sources_used`` shape so a
    non-redistributable witness (for example a DSS CC-BY-NC-4.0 source) folds
    into ``response_safe_to_share``. A missing sidecar yields the empty block
    (most of the 231 questions carry no attestation). The question_id is
    validated here so a directly imported call cannot traverse outside the
    historical directory.
    """
    qid = validate_question_id(qid)
    path = (historical_dir or HISTORICAL_DIR) / f"{qid}.json"
    if not path.exists():
        return _empty_historical_block(), []
    attestation = HistoricalAttestation.model_validate(json.loads(path.read_text(encoding="utf-8")))
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


# ---------------------------------------------------------------------------
# Lexical block (Pipeline 2 evidence) and proposition classification
# ---------------------------------------------------------------------------


def _build_lexical_block(evidence: dict[str, Any], qid: str) -> dict[str, Any]:
    """Assemble the lexical-evidence block from the stored evidence file."""
    verdict = evidence.get("verdict", {})
    lexical = dict(evidence.get("lexical_evidence", {}) or {})
    lexical.update(
        {
            "rationale": verdict.get("rationale"),
            "lay_summary": evidence.get("lay_summary"),
            "pan_canonical": verdict.get("pan_canonical"),
            "variant_robust": verdict.get("variant_robust"),
            "source_evidence_files": [f"evidence/{qid}.json"],
        }
    )
    return lexical


def _classify_to_question_id(proposition: str) -> str:
    """Map proposition prose to a question_id by keyword overlap with questions.json."""
    questions_path = Path("questions.json")
    if not questions_path.exists():
        return ""
    raw = json.loads(questions_path.read_text(encoding="utf-8"))
    needle = proposition.lower()
    best_qid = ""
    best_score = 0
    for q in raw.get("questions", []):
        statement = (q.get("statement", "") or "").lower()
        score = sum(1 for word in needle.split() if word in statement)
        if score > best_score:
            best_score = score
            best_qid = q["id"]
    return best_qid


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handle(
    payload: DoctrinalVerdictInput,
    *,
    evidence_dir: Path | None = None,
    historical_dir: Path | None = None,
    cultural_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the three diagnostic blocks for the proposition.

    ``cultural_chunks`` is supplied by the server from a live cultural retrieval;
    when absent the cultural overlay is empty. Both diagnostic blocks are
    optional and never change the lexical verdict.
    """
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
            f"historical sidecar for {qid}: {exc}",
            payload.caller_context,
        )

    cultural_block, cultural_sources = build_cultural_overlay(cultural_chunks)

    verdict = evidence.get("verdict", {})
    result = {
        "verdict": verdict.get("affirms"),
        "lexical_breadth": verdict.get("lexical_breadth"),
        "lexical_directness": verdict.get("lexical_directness"),
        "variant_stability": verdict.get("variant_stability"),
        "lexical_evidence": _build_lexical_block(evidence, qid),
        "cultural_overlay": cultural_block,
        "variant_sensitivity": evidence.get("variants", {}),
        "historical_attestation": historical_block,
        "evidence_file_id": qid,
    }

    sources = [
        {"source": s.get("source", "?"), "license": s.get("license", "?")}
        for s in evidence.get("license_audit", {}).get("sources_used", [])
    ]
    sources.extend(cultural_sources)
    sources.extend(historical_sources)

    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(
        name=TOOL_NAME,
        description="Doctrinal verdict: lexical verdict plus cultural and historical diagnostics.",
    )
    def _tool(
        ctx: Context,
        proposition: str,
        denominations: list[str] | None = None,
        depth: Literal["fast", "deep"] = "fast",
        progressToken: str | None = None,  # noqa: N803
        caller_context: CallerContext = "personal",
    ) -> dict[str, Any]:
        payload = DoctrinalVerdictInput(
            proposition=proposition,
            denominations=denominations,
            depth=depth,
            progressToken=progressToken,
            caller_context=caller_context,
        )
        qid = _classify_to_question_id(proposition)
        chunks = retrieve_chunks(
            ctx, question_id=qid or None, doctrine=proposition, traditions=denominations, k=8
        )
        return handle(payload, cultural_chunks=chunks)
