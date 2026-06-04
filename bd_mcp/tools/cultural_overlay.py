"""cultural_overlay: tradition passages with license-aware snippet redaction."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from bd_mcp.tools._common import ToolInputBase, success_envelope

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


def handle(
    payload: CulturalOverlayInput,
    cultural_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    chunks = list(cultural_chunks or [])
    passages: list[dict[str, Any]] = []
    sources_used: list[dict[str, str]] = []
    for ch in chunks[: payload.k]:
        license_ = ch.get("license", "<unknown>")
        redistribute = bool(ch.get("redistribute", False))
        source_word_count = int(ch.get("source_work_word_count", 0))
        text = ch.get("text", "")
        snippet = _redact_snippet(text, source_word_count, redistribute)
        paraphrase = None
        if not redistribute:
            paraphrase = _paraphrase(text)
        passages.append(
            {
                "tradition": ch.get("tradition"),
                "source": ch.get("source"),
                "stance": ch.get("stance"),
                "snippet": snippet,
                "tradition_paraphrase_if_not_redistributable": paraphrase,
            }
        )
        sources_used.append({"source": ch.get("source", "<unknown>"), "license": license_})
    result = {
        "ref": payload.ref,
        "doctrine": payload.doctrine,
        "passages": passages,
        "by_tradition": _by_tradition(passages),
    }
    snippet_words = sum(len((p["snippet"] or "").split()) for p in passages)
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources_used,
        caller_context=payload.caller_context,
        snippet_word_count=snippet_words,
        source_work_word_count=max(
            (int(c.get("source_work_word_count", 0)) for c in chunks),
            default=100000,
        ),
    )


def _by_tradition(passages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for p in passages:
        out.setdefault(p.get("tradition", "unknown"), []).append(p)
    return out


def register(server: Any, cultural_retriever: Any | None = None) -> None:
    @server.tool(
        name=TOOL_NAME, description="Cultural-store tradition passages with license-aware snippets."
    )
    def _tool(
        ref: str | None = None,
        doctrine: str | None = None,
        traditions: list[str] | None = None,
        k: int = 8,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = CulturalOverlayInput(
            ref=ref,
            doctrine=doctrine,
            traditions=traditions,
            k=k,
            caller_context=caller_context,
        )
        if cultural_retriever is None:
            return handle(payload)
        try:
            chunks = cultural_retriever(doctrine=doctrine, ref=ref, traditions=traditions, k=k)
        except Exception:  # noqa: BLE001  cultural overlay is diagnostic, degrade to empty
            chunks = None
        return handle(payload, cultural_chunks=chunks)
