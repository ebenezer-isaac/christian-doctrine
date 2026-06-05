"""concordance_walk: enumerate occurrences of a Strong's code or lemma."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field, model_validator

from bd_mcp.runtime import lexical_session
from bd_mcp.tools._common import ToolInputBase, success_envelope

TOOL_NAME = "concordance_walk"


class ConcordanceWalkInput(ToolInputBase):
    strong: str | None = None
    lemma: str | None = None
    window: int = Field(default=5, ge=0, le=30)
    filter_book: list[str] | None = None
    limit: int = Field(default=200, ge=1, le=2000)

    @model_validator(mode="after")
    def at_least_one_anchor(self) -> ConcordanceWalkInput:
        if not self.strong and not self.lemma:
            raise ValueError("either strong or lemma must be provided")
        return self


# Live lexical graph schema (confirmed against bolt://localhost:7688):
#   - The prior cypher used (:Lemma)<-[:INSTANCE_OF]-(:Word)-[:IN_VERSE]->
#     (:Verse) and returned v.osisID. That breaks twice: osisID is OT-only
#     (NULL for the entire NT), and the MACULA Greek Word carries no IN_VERSE
#     edge and no Strong, so Greek concordance returned nothing.
#   - Greek occurrences are read from STEPBible TAGNT tagged tokens, which DO
#     carry IN_VERSE to :Verse plus the inflected surface (.greek) and the
#     parse (.dstrongs_grammar): (:TaggedToken{source:'STEPBible-TAGNT'})
#     -[:INSTANCE_OF]->(:GreekLemma) and -[:IN_VERSE]->(:Verse). DISTINCT on
#     the token id collapses the duplicate Nestle/SBLGNT lemma editions.
#   - Hebrew occurrences are read from OSHB words, which carry the base Strong,
#     IN_VERSE, .surface and .morph: (:Word{source:'OSHB-morphology'})
#     -[:IN_VERSE]->(:Verse).
#   - The verse ref is v.osis (universal BCV, populated for both testaments).
# Both branches alias ref/surface/morph so the handler record contract
# (rec["ref"], rec["surface"], rec["morph"]) holds for live and fixture callers.
_CONCORDANCE_BY_STRONG = (
    "WITH $anchor AS anchor "
    "CALL (anchor) { "
    "  WITH anchor "
    "  MATCH (t:TaggedToken {source: 'STEPBible-TAGNT'})"
    "-[:INSTANCE_OF]->(:GreekLemma {strong: anchor}) "
    "  MATCH (t)-[:IN_VERSE]->(v:Verse) "
    "  RETURN DISTINCT t.id AS tok, v.osis AS ref, "
    "         coalesce(t.greek, '') AS surface, "
    "         coalesce(t.dstrongs_grammar, '') AS morph "
    "  UNION "
    "  WITH anchor "
    "  MATCH (w:Word {source: 'OSHB-morphology'})-[:IN_VERSE]->(v:Verse) "
    "  WHERE w.strong = anchor "
    "  RETURN w.id AS tok, v.osis AS ref, "
    "         coalesce(w.surface, '') AS surface, "
    "         coalesce(w.morph, '') AS morph "
    "} "
    "RETURN ref, surface, morph ORDER BY tok LIMIT $lim"
)

_CONCORDANCE_BY_LEMMA = (
    "WITH $anchor AS anchor "
    "CALL (anchor) { "
    "  WITH anchor "
    "  MATCH (gl:GreekLemma {lemma: anchor})"
    "<-[:INSTANCE_OF]-(t:TaggedToken {source: 'STEPBible-TAGNT'}) "
    "  MATCH (t)-[:IN_VERSE]->(v:Verse) "
    "  RETURN DISTINCT t.id AS tok, v.osis AS ref, "
    "         coalesce(t.greek, '') AS surface, "
    "         coalesce(t.dstrongs_grammar, '') AS morph "
    "  UNION "
    "  WITH anchor "
    "  MATCH (l:Lemma {lemma: anchor}) "
    "  MATCH (w:Word {source: 'OSHB-morphology'})-[:IN_VERSE]->(v:Verse) "
    "  WHERE w.strong = l.strong "
    "  RETURN w.id AS tok, v.osis AS ref, "
    "         coalesce(w.surface, '') AS surface, "
    "         coalesce(w.morph, '') AS morph "
    "} "
    "RETURN ref, surface, morph ORDER BY tok LIMIT $lim"
)


def handle(payload: ConcordanceWalkInput, neo4j_session: Any | None = None) -> dict[str, Any]:
    occurrences: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    if neo4j_session is not None:
        if payload.strong:
            cypher = _CONCORDANCE_BY_STRONG
            params = {"anchor": payload.strong, "lim": payload.limit}
        else:
            cypher = _CONCORDANCE_BY_LEMMA
            params = {"anchor": payload.lemma, "lim": payload.limit}
        for rec in neo4j_session.run(cypher, **params):
            ref = rec["ref"]
            if payload.filter_book and not any(
                ref.startswith(b + ".") for b in payload.filter_book
            ):
                continue
            occurrences.append(
                {
                    "ref": ref,
                    "surface": rec["surface"],
                    "morph": rec["morph"],
                    "context_left": "",
                    "context_right": "",
                }
            )
        # Greek occurrences are read from STEPBible TAGNT, Hebrew from OSHB.
        # Both are open-licensed (CC-BY-4.0). Attribute both since the anchor
        # may resolve to either testament.
        sources.append({"source": "STEPBible-TAGNT", "license": "CC-BY-4.0"})
        sources.append({"source": "OSHB-morphology", "license": "CC-BY-4.0"})
    result = {
        "anchor": payload.strong or payload.lemma,
        "occurrences": occurrences,
        "truncated": len(occurrences) >= payload.limit,
    }
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(name=TOOL_NAME, description="Concordance walk over a Strong's code or lemma.")
    def _tool(
        ctx: Context,
        strong: str | None = None,
        lemma: str | None = None,
        window: int = 5,
        filter_book: list[str] | None = None,
        limit: int = 200,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = ConcordanceWalkInput(
            strong=strong,
            lemma=lemma,
            window=window,
            filter_book=filter_book,
            limit=limit,
            caller_context=caller_context,
        )
        with lexical_session(ctx) as session:
            return handle(payload, neo4j_session=session)
