"""cross_ref: OpenBible / TSK cross-references for a verse."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from cd_mcp.runtime import lexical_session
from cd_mcp.tools._common import ToolInputBase, success_envelope

TOOL_NAME = "cross_ref"


class CrossRefInput(ToolInputBase):
    ref: str = Field(min_length=1)
    sources: list[str] | None = None
    min_votes: int | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


# Live lexical graph schema (confirmed against bolt://localhost:7688):
#   - The prior cypher matched (:CrossRef {from_ref}) and read cr.votes /
#     cr.source. That only ever sees TSK: :CrossRef nodes in this store are
#     all source 'TSK' and carry NO votes property (so every edge collapsed to
#     votes=1). The OpenBible vote-weighted cross references live elsewhere.
#   - OpenBible cross refs are verse-to-verse relationships, not nodes:
#     (:Verse)-[:OPENBIBLE_CROSS_REF {to_osis, votes, source, from_osis}]->
#     (:Verse). These carry real community vote counts (e.g. John.3.16 ->
#     Rom.5.8 = 962 votes), which min_votes filtering needs.
#   - TSK cross refs remain (:CrossRef {from_ref, to_ref, source:'TSK'}) with
#     no vote weight, so they default to votes=1.
# The two systems are UNION-ed. The source label is normalised to the lower
# case slugs the handler keys on ('openbible' / 'tsk'). Verses anchor on
# Verse.id ('verse:' + osis); the handler reads rec["from_ref"], rec["to_ref"],
# rec["source"], rec["votes"], preserved for live and fixture callers.
_CROSS_REF_CYPHER = (
    "CALL (ref) { "
    "  WITH ref "
    "  MATCH (v:Verse {id: 'verse:' + ref})-[e:OPENBIBLE_CROSS_REF]->(t:Verse) "
    "  RETURN ref AS from_ref, t.osis AS to_ref, 'openbible' AS source, "
    "         coalesce(e.votes, 1) AS votes "
    "  UNION "
    "  WITH ref "
    "  MATCH (cr:CrossRef {from_ref: ref}) "
    "  RETURN cr.from_ref AS from_ref, cr.to_ref AS to_ref, 'tsk' AS source, "
    "         coalesce(cr.votes, 1) AS votes "
    "} "
    "WITH from_ref, to_ref, source, votes "
    "WHERE ($min_votes IS NULL OR votes >= $min_votes) "
    "  AND ($sources IS NULL OR source IN $sources) "
    "RETURN from_ref, to_ref, source, votes "
    "ORDER BY votes DESC, to_ref LIMIT $lim"
)


def handle(payload: CrossRefInput, neo4j_session: Any | None = None) -> dict[str, Any]:
    edges: list[dict[str, Any]] = []
    sources_used: list[dict[str, str]] = []
    if neo4j_session is not None:
        for rec in neo4j_session.run(
            "WITH $ref AS ref " + _CROSS_REF_CYPHER,
            ref=payload.ref,
            min_votes=payload.min_votes,
            sources=payload.sources,
            lim=payload.limit,
        ):
            edges.append(
                {
                    "from": rec["from_ref"],
                    "to": rec["to_ref"],
                    "source": rec["source"],
                    "votes": rec["votes"],
                }
            )
        if any(e["source"] == "openbible" for e in edges):
            sources_used.append({"source": "OpenBible-cross-refs", "license": "CC-BY"})
        if any(e["source"] == "tsk" for e in edges):
            sources_used.append({"source": "TSK", "license": "public_domain"})
    result = {"ref": payload.ref, "edges": edges, "count": len(edges)}
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources_used,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(name=TOOL_NAME, description="Cross-references for a verse.")
    def _tool(
        ctx: Context,
        ref: str,
        sources: list[str] | None = None,
        min_votes: int | None = None,
        limit: int = 50,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = CrossRefInput(
            ref=ref,
            sources=sources,
            min_votes=min_votes,
            limit=limit,
            caller_context=caller_context,
        )
        with lexical_session(ctx) as session:
            return handle(payload, neo4j_session=session)
