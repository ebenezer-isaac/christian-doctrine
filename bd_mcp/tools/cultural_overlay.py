"""cultural_overlay: tradition passages with license-aware snippet redaction.

The handler is a pure transform over cultural chunks. ``build_cultural_overlay``
is the shared formatter (also used by ``doctrinal_verdict``) that turns retrieved
chunks into license-redacted passages grouped by tradition.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from pydantic import Field

from bd_mcp.runtime import cultural_chunks as retrieve_chunks
from bd_mcp.tools._common import CallerContext, ToolInputBase, success_envelope

TOOL_NAME = "cultural_overlay"

SNIPPET_WORD_CAP = 100


class CulturalOverlayInput(ToolInputBase):
    ref: str | None = None
    doctrine: str | None = None
    traditions: list[str] | None = None
    k: int = Field(default=8, ge=1, le=50)


def _redact_snippet(text: str, source_work_word_count: int, redistribute: bool) -> str | None:
    if redistribute:
        return text
    words = text.split()
    if not words:
        return None
    one_percent_cap = max(1, source_work_word_count // 100) if source_work_word_count > 0 else 0
    effective_cap = (
        min(SNIPPET_WORD_CAP, one_percent_cap) if one_percent_cap > 0 else SNIPPET_WORD_CAP
    )
    if effective_cap <= 0:
        return None
    return " ".join(words[:effective_cap])


def _paraphrase(text: str) -> str:
    words = text.split()
    return " ".join(words[:30]) + (" ..." if len(words) > 30 else "")


def _by_tradition(passages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for p in passages:
        out.setdefault(p.get("tradition", "unknown"), []).append(p)
    return out


def build_cultural_overlay(
    chunks: list[dict[str, Any]] | None,
    *,
    k: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Format cultural chunks into license-redacted passages grouped by tradition.

    Returns ``({"passages": [...], "by_tradition": {...}}, sources_used)``. A
    redistribute=false chunk is snippet-capped (100 words and 1% of the source
    work) and paraphrased; a redistributable chunk is returned in full. Shared by
    cultural_overlay and doctrinal_verdict so both render the overlay identically.
    """
    selected = list(chunks or [])
    if k is not None:
        selected = selected[:k]
    passages: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    for ch in selected:
        redistribute = bool(ch.get("redistribute", False))
        text = ch.get("text", "")
        snippet = _redact_snippet(text, int(ch.get("source_work_word_count", 0)), redistribute)
        passages.append(
            {
                "tradition": ch.get("tradition"),
                "source": ch.get("source"),
                "stance": ch.get("stance"),
                "snippet": snippet,
                "tradition_paraphrase_if_not_redistributable": (
                    None if redistribute else _paraphrase(text)
                ),
            }
        )
        sources.append(
            {"source": ch.get("source", "<unknown>"), "license": ch.get("license", "<unknown>")}
        )
    return {"passages": passages, "by_tradition": _by_tradition(passages)}, sources


def handle(
    payload: CulturalOverlayInput,
    cultural_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    chunks = list(cultural_chunks or [])
    block, sources_used = build_cultural_overlay(chunks, k=payload.k)
    result = {"ref": payload.ref, "doctrine": payload.doctrine, **block}
    snippet_words = sum(len((p["snippet"] or "").split()) for p in block["passages"])
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources_used,
        caller_context=payload.caller_context,
        snippet_word_count=snippet_words,
        source_work_word_count=max(
            (int(c.get("source_work_word_count", 0)) for c in chunks), default=100000
        ),
    )


def register(server: Any) -> None:
    @server.tool(
        name=TOOL_NAME, description="Cultural-store tradition passages with license-aware snippets."
    )
    def _tool(
        ctx: Context,
        ref: str | None = None,
        doctrine: str | None = None,
        traditions: list[str] | None = None,
        k: int = 8,
        caller_context: CallerContext = "personal",
    ) -> dict[str, Any]:
        payload = CulturalOverlayInput(
            ref=ref, doctrine=doctrine, traditions=traditions, k=k, caller_context=caller_context
        )
        chunks = retrieve_chunks(ctx, doctrine=doctrine, ref=ref, traditions=traditions, k=k)
        return handle(payload, cultural_chunks=chunks)
