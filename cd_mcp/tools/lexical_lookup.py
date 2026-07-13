"""lexical_lookup: Strong's / lemma / surface / gloss lookup against the lexical store."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from cd_mcp.runtime import lexical_session
from cd_mcp.tools._common import ToolInputBase, success_envelope

TOOL_NAME = "lexical_lookup"


class LexicalLookupInput(ToolInputBase):
    query: str = Field(min_length=1)
    lang: Literal["hb", "gk"]
    id_type: Literal["strong", "lemma", "surface", "gloss"] = "strong"
    limit: int = Field(default=20, ge=1, le=200)


# Live lexical graph schema (confirmed against bolt://localhost:7688):
#   - Greek lemmas live on :GreekLemma, Hebrew on :Lemma; both carry
#     .strong (e.g. 'G2316', 'H0430') and .lemma (the lexeme surface). The
#     prior cypher matched :Lemma only, so every Greek strong (incl. G2316
#     theos) returned nothing.
#   - .transliteration, .gloss and .occurrences_in_canon do NOT live on the
#     lemma node. Gloss + transliteration come from :BriefLexEntry (STEPBible
#     TBESG/TBESH) keyed by .base_strong and linked via (:BriefLexEntry)
#     -[:LEX_FOR]->(lemma); .greek / .hebrew hold the unaccented headword.
#   - occurrences_in_canon is the distinct tagged-token count: Greek tokens
#     are :TaggedToken{source:'STEPBible-TAGNT'}-[:INSTANCE_OF]->:GreekLemma;
#     Hebrew occurrences are best counted on :Word{source:'OSHB-morphology'}
#     whose .strong carries the base Strong (TAHOT tokens carry a disambig
#     suffix so they do not join the base-strong lemma node cleanly).
# Each branch RETURNs a single map aliased `l` so the handler's record
# contract (rec["l"] -> dict with strong/lemma/transliteration/gloss/
# occurrences_in_canon) is preserved for both live and fixture callers.
# Self-contained occurrence-count subquery. Imports `strong` from the outer
# scope and returns a single `occurrences_in_canon` value. Each UNION branch
# re-imports `strong` with its own WITH (Neo4j scoped-subquery rule). Counting
# spans Greek tagged tokens and Hebrew OSHB words; the two are summed.
_OCC_SUBQUERY = (
    "CALL (strong) { "
    "  WITH strong "
    "  MATCH (t:TaggedToken)-[:INSTANCE_OF]->(lc) "
    "  WHERE (lc:Lemma OR lc:GreekLemma) AND lc.strong = strong "
    "  RETURN count(DISTINCT t) AS c "
    "  UNION "
    "  WITH strong "
    "  MATCH (w:Word {source: 'OSHB-morphology'}) WHERE w.strong = strong "
    "  RETURN count(w) AS c "
    "} "
    "WITH strong, lemma_raw, lex, sum(c) AS occurrences_in_canon "
)

# Shared projection of the lexeme map aliased `l`, so the handler's record
# contract (rec["l"] -> dict with strong/lemma/transliteration/gloss/
# occurrences_in_canon) holds for both live and fixture callers.
_PROJECT_L = (
    " RETURN { strong: strong, "
    "  lemma: coalesce(lex.greek, lex.hebrew, lemma_raw), "
    "  transliteration: lex.transliteration, "
    "  gloss: lex.english, "
    "  occurrences_in_canon: occurrences_in_canon } AS l "
    "LIMIT $lim"
)

_LOOKUP_BY_STRONG = (
    "MATCH (l) WHERE (l:Lemma OR l:GreekLemma) AND l.strong = $q "
    "WITH l.strong AS strong, head(collect(l.lemma)) AS lemma_raw "
    "OPTIONAL MATCH (e:BriefLexEntry {base_strong: strong}) "
    "WITH strong, lemma_raw, head(collect(e)) AS lex " + _OCC_SUBQUERY + _PROJECT_L
)

_LOOKUP_BY_LEMMA = (
    "MATCH (l) WHERE (l:Lemma OR l:GreekLemma) AND l.lemma = $q "
    "WITH l.strong AS strong, head(collect(l.lemma)) AS lemma_raw "
    "WHERE strong IS NOT NULL "
    "OPTIONAL MATCH (e:BriefLexEntry {base_strong: strong}) "
    "WITH strong, lemma_raw, head(collect(e)) AS lex " + _OCC_SUBQUERY + _PROJECT_L
)

# Surface lookup resolves a token surface form back to its lexeme. Greek
# surfaces sit on :Word{source:'MACULA-Greek-SBLGNT'}.text with INSTANCE_OF
# to :GreekLemma; Hebrew surfaces sit on :Word{source:'OSHB-morphology'}
# .surface whose .strong joins the base lemma node.
_LOOKUP_BY_SURFACE = (
    "MATCH (w:Word) WHERE coalesce(w.text, w.surface) = $q "
    "OPTIONAL MATCH (w)-[:INSTANCE_OF]->(gl) WHERE gl:GreekLemma OR gl:Lemma "
    "WITH coalesce(gl.strong, w.strong) AS strong, "
    "     head(collect(coalesce(gl.lemma, w.lemma))) AS lemma_raw "
    "WHERE strong IS NOT NULL "
    "OPTIONAL MATCH (e:BriefLexEntry {base_strong: strong}) "
    "WITH strong, lemma_raw, head(collect(e)) AS lex " + _OCC_SUBQUERY + _PROJECT_L
)

# Gloss search scans :BriefLexEntry English glosses (the only place a free-text
# gloss lives) and resolves the matched entry back to its lexeme via .base_strong.
_LOOKUP_BY_GLOSS = (
    "MATCH (e:BriefLexEntry) WHERE e.english CONTAINS $q "
    "WITH e.base_strong AS strong, head(collect(e)) AS lex "
    "WHERE strong IS NOT NULL "
    "OPTIONAL MATCH (l) WHERE (l:Lemma OR l:GreekLemma) AND l.strong = strong "
    "WITH strong, lex, head(collect(l.lemma)) AS lemma_raw " + _OCC_SUBQUERY + _PROJECT_L
)


def handle(payload: LexicalLookupInput, neo4j_session: Any | None = None) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    if neo4j_session is not None:
        cypher_by_type = {
            "strong": _LOOKUP_BY_STRONG,
            "lemma": _LOOKUP_BY_LEMMA,
            "surface": _LOOKUP_BY_SURFACE,
            "gloss": _LOOKUP_BY_GLOSS,
        }
        cypher = cypher_by_type[payload.id_type]
        for rec in neo4j_session.run(cypher, q=payload.query, lim=payload.limit):
            lemma = dict(rec["l"])
            matches.append(
                {
                    "strong": lemma.get("strong"),
                    "lemma": lemma.get("lemma"),
                    "transliteration": lemma.get("transliteration"),
                    "occurrences_in_canon": lemma.get("occurrences_in_canon"),
                    "gloss": lemma.get("gloss"),
                }
            )
        source_slug = "STEPBible-TBESH" if payload.lang == "hb" else "STEPBible-TBESG"
        sources.append({"source": source_slug, "license": "CC-BY-4.0"})
    result = {
        "query": payload.query,
        "lang": payload.lang,
        "id_type": payload.id_type,
        "matches": matches,
        "truncated": len(matches) >= payload.limit,
    }
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(
        name=TOOL_NAME, description="Strong's / lemma / surface lookup in the lexical store."
    )
    def _tool(
        ctx: Context,
        query: str,
        lang: Literal["hb", "gk"],
        id_type: Literal["strong", "lemma", "surface", "gloss"] = "strong",
        limit: int = 20,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = LexicalLookupInput(
            query=query,
            lang=lang,
            id_type=id_type,
            limit=limit,
            caller_context=caller_context,
        )
        with lexical_session(ctx) as session:
            return handle(payload, neo4j_session=session)
