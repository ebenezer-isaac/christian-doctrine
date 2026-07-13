"""debate_for_verse: by-tradition stances grouped by doctrine for a single verse."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from cd_mcp.runtime import cultural_chunks as retrieve_chunks
from cd_mcp.tools._common import ToolInputBase, success_envelope
from cd_mcp.tools.cultural_overlay import _redact_snippet

TOOL_NAME = "debate_for_verse"


class DebateForVerseInput(ToolInputBase):
    ref: str = Field(min_length=1)
    doctrines: list[str] | None = None


def handle(
    payload: DebateForVerseInput,
    cultural_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    chunks = list(cultural_chunks or [])
    by_tradition: dict[str, list[dict[str, Any]]] = {}
    sources_used: list[dict[str, str]] = []
    for ch in chunks:
        snippet = _redact_snippet(
            ch.get("text", ""),
            int(ch.get("source_work_word_count", 0)),
            bool(ch.get("redistribute", False)),
        )
        by_tradition.setdefault(ch.get("tradition", "unknown"), []).append(
            {
                "source": ch.get("source"),
                "stance": ch.get("stance"),
                "snippet": snippet,
            }
        )
        sources_used.append(
            {"source": ch.get("source", "<unknown>"), "license": ch.get("license", "<unknown>")}
        )
    result = {
        "ref": payload.ref,
        "by_tradition": by_tradition,
    }
    snippet_words = sum(
        len((p["snippet"] or "").split()) for ps in by_tradition.values() for p in ps
    )
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources_used,
        caller_context=payload.caller_context,
        snippet_word_count=snippet_words,
        source_work_word_count=100000,
    )


def register(server: Any) -> None:
    @server.tool(name=TOOL_NAME, description="Tradition-grouped stances for a verse.")
    def _tool(
        ctx: Context,
        ref: str,
        doctrines: list[str] | None = None,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = DebateForVerseInput(ref=ref, doctrines=doctrines, caller_context=caller_context)
        chunks = retrieve_chunks(
            ctx, ref=ref, doctrine=(doctrines[0] if doctrines else None), traditions=None, k=12
        )
        return handle(payload, cultural_chunks=chunks)
