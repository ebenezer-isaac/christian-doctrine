"""FastMCP server entry point.

All 12 tools register against one server. Store connections are opened by the
lifespan (``bd_mcp.runtime``) and reached by each tool through the injected
Context, so the server is fully functional with no external wiring:
``python -m bd_mcp.server`` serves every tool live against the real stores.

The tools return structured data. The lexical verdict is authoritative (read
verbatim from the evidence files), the cultural overlay and historical
attestation ride alongside as diagnostics, and the calling model reasons over
the three. The server never calls an LLM of its own.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from bd_mcp.runtime import lifespan
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


def build_server() -> Any:
    """Build the server with all 12 tools registered and the live-store lifespan."""
    server = FastMCP(
        name="brethren-doctrine",
        instructions=(
            "Manuscript-anchored biblical doctrine engine. Lexical verdicts derive from "
            "apparatus + interlinear + concordance only. Cultural overlay is diagnostic; "
            "it never settles a verdict. License audit accompanies every response."
        ),
        lifespan=lifespan,
    )
    register_lexical_lookup(server)
    register_concordance_walk(server)
    register_cross_ref(server)
    register_variant_inspect(server)
    register_parallel_translation(server)
    register_versification_resolve(server)
    register_cultural_overlay(server)
    register_debate_for_verse(server)
    register_doctrinal_verdict(server)
    register_evidence_inspect(server)
    register_historical_inspect(server)
    register_license_audit(server)
    return server


def main() -> None:
    server = build_server()
    server.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
    server.settings.port = int(os.environ.get("MCP_PORT", "8765"))
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
