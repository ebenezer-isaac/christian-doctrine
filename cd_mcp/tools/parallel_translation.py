"""parallel_translation: side-by-side translation lookup with license-aware snippet redaction."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from cd_mcp.runtime import lexical_session
from cd_mcp.tools._common import ToolInputBase, success_envelope

TOOL_NAME = "parallel_translation"


def _record_section(rec: Any) -> str | None:
    """Read the canon_section value off a result record, tolerating absence.

    Live Neo4j records carry a `section` key; fixture stub records may not.
    Returns None when the key is missing rather than raising, so the original
    text still flows through with a Greek default.
    """
    try:
        return rec["section"]
    except (KeyError, IndexError, TypeError):
        return None


class ParallelTranslationInput(ToolInputBase):
    ref: str = Field(min_length=1)
    translations: list[str] = Field(min_length=1)
    include_original: bool = True


def handle(
    payload: ParallelTranslationInput,
    neo4j_session: Any | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources_used: list[dict[str, str]] = []
    if payload.include_original and neo4j_session is not None:
        # Live lexical graph schema (confirmed against bolt://localhost:7688):
        #   - The prior cypher walked (:Verse {osisID})-[:HAS_WORD]->(:Word).
        #     That breaks twice: osisID is OT-only (NULL for the entire NT), and
        #     there is no HAS_WORD edge from Verse to the MACULA words in this
        #     store, so the original text came back empty for every verse.
        #   - The original Greek / Hebrew text is materialised directly on the
        #     verse node: :Verse{id:'verse:'+osis}.text holds the full
        #     accented verse string (Greek for NT, pointed Hebrew for OT), with
        #     .canon_section in {'NT','OT'}. We read it in one shot.
        # One record aliased `surface` carries the full text; the handler joins
        # rec["surface"] with spaces, so a single row yields the verse verbatim.
        cypher = (
            "MATCH (v:Verse {id: 'verse:' + $ref}) "
            "RETURN coalesce(v.text, '') AS surface, v.canon_section AS section"
        )
        records = list(neo4j_session.run(cypher, ref=payload.ref))
        original = " ".join(rec["surface"] or "" for rec in records)
        section = _record_section(records[0]) if records else None
        if original.strip():
            lang = "hb" if section == "OT" else "gk"
            rows.append({"translation": "original", "text": original, "lang": lang})
            # OT verse text is OSHB (CC-BY-4.0); NT verse text is MACULA Greek
            # SBLGNT (CC-BY-4.0). Attribute by the verse's canon section.
            if lang == "hb":
                sources_used.append({"source": "OSHB-text", "license": "CC-BY-4.0"})
            else:
                sources_used.append({"source": "MACULA-Greek-SBLGNT", "license": "CC-BY-4.0"})
    for code in payload.translations:
        rows.append({"translation": code, "text": f"(translation lookup pending for {code})"})
        if code.upper() in {"ESV", "TTESV"}:
            sources_used.append({"source": "STEPBible-TTESV", "license": "CC-BY-NC-4.0"})
        else:
            sources_used.append({"source": f"translation-{code}", "license": "fair-use-policy"})
    result = {"ref": payload.ref, "rows": rows}
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources_used,
        caller_context=payload.caller_context,
        snippet_word_count=len(" ".join(r["text"] for r in rows).split()),
        source_work_word_count=600000,
    )


def register(server: Any) -> None:
    @server.tool(name=TOOL_NAME, description="Side-by-side parallel translation rows.")
    def _tool(
        ctx: Context,
        ref: str,
        translations: list[str],
        include_original: bool = True,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = ParallelTranslationInput(
            ref=ref,
            translations=translations,
            include_original=include_original,
            caller_context=caller_context,
        )
        with lexical_session(ctx) as session:
            return handle(payload, neo4j_session=session)
