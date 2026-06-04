"""FastMCP server entry point.

Tool registrations are imported lazily so unit tests can instantiate the server
without dragging the full Neo4j / Qdrant runtime in.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from bd_mcp.tools.concordance_walk import register as register_concordance_walk
from bd_mcp.tools.cross_ref import register as register_cross_ref
from bd_mcp.tools.cultural_overlay import register as register_cultural_overlay
from bd_mcp.tools.debate_for_verse import register as register_debate_for_verse
from bd_mcp.tools.doctrinal_verdict import register as register_doctrinal_verdict
from bd_mcp.tools.evidence_inspect import register as register_evidence_inspect
from bd_mcp.tools.historical_inspect import register as register_historical_inspect
from bd_mcp.tools.lexical_lookup import register as register_lexical_lookup
from bd_mcp.tools.license_audit import register as register_license_audit
from bd_mcp.tools.parallel_translation import register as register_parallel_translation
from bd_mcp.tools.variant_inspect import register as register_variant_inspect
from bd_mcp.tools.versification_resolve import register as register_versification_resolve

TOOL_NAMES = (
    "lexical_lookup",
    "concordance_walk",
    "cross_ref",
    "variant_inspect",
    "parallel_translation",
    "versification_resolve",
    "cultural_overlay",
    "debate_for_verse",
    "doctrinal_verdict",
    "evidence_inspect",
    "historical_inspect",
    "license_audit",
)


def build_server(
    *,
    lexical_session_factory: Any | None = None,
    cultural_retriever: Any | None = None,
    synthesis_fn: Any | None = None,
) -> Any:
    """Register all 12 tools.

    With no injectors (the default), the tools run as pure skeletons: they
    validate inputs and return well-formed empty results, which is what the unit
    suite exercises. ``main()`` passes the live injectors so the served tools
    query the real stores. The query-time air-gap holds in the wiring itself:
    the lexical session factory reaches only the lexical store, the cultural
    retriever only the cultural store, and the historical block is a filesystem
    read of the locked sidecar.
    """
    server = FastMCP(
        name="brethren-doctrine",
        instructions=(
            "Manuscript-anchored biblical doctrine engine. Lexical verdicts derive from "
            "apparatus + interlinear + concordance only. Cultural overlay is diagnostic; "
            "it never settles a verdict. License audit accompanies every response."
        ),
    )
    register_lexical_lookup(server, lexical_session_factory)
    register_concordance_walk(server, lexical_session_factory)
    register_cross_ref(server, lexical_session_factory)
    register_variant_inspect(server)
    register_parallel_translation(server, lexical_session_factory)
    register_versification_resolve(server)
    register_cultural_overlay(server, cultural_retriever)
    register_debate_for_verse(server, cultural_retriever)
    register_doctrinal_verdict(server, synthesis_fn)
    register_evidence_inspect(server)
    register_historical_inspect(server)
    register_license_audit(server)
    return server


def build_live_injectors() -> dict[str, Any]:
    """Construct the live-store injectors for the served tools.

    The lexical session factory is wired only when the lexical store answers, so
    a down store degrades to the skeleton path instead of erroring per request.
    The cultural retriever is fail-soft by contract, so it is always wired.
    ``synthesis_fn`` stays None here: the standalone server has no orchestrator
    to provide a subagent dispatch_fn (there is no programmatic Anthropic API),
    so doctrinal_verdict serves the deterministic verdict path with the live
    historical block. An orchestrator that drives the server injects its own
    synthesis_fn via build_server.
    """
    from bd_mcp.live.cultural import retrieve_cultural_chunks
    from bd_mcp.live.lexical import lexical_session_factory, lexical_store_reachable

    lex_factory = lexical_session_factory() if lexical_store_reachable() else None
    return {
        "lexical_session_factory": lex_factory,
        "cultural_retriever": retrieve_cultural_chunks,
        "synthesis_fn": None,
    }


def main() -> None:
    server = build_server(**build_live_injectors())
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8765"))
    server.settings.host = host
    server.settings.port = port
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
