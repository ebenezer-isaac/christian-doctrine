"""FastMCP server entry point.

All 12 tools register against one server. Store connections are opened by the
lifespan (``cd_mcp.runtime``) and reached by each tool through the injected
Context, so the server is fully functional with no external wiring:
``python -m cd_mcp.server`` serves every tool live against the real stores.

The tools return structured data. The lexical verdict is authoritative (read
verbatim from the evidence files), the cultural overlay and historical
attestation ride alongside as diagnostics, and the calling model reasons over
the three. The server never calls an LLM of its own.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from cd_mcp.runtime import lifespan
from cd_mcp.tools.concordance_walk import register as register_concordance_walk
from cd_mcp.tools.cross_ref import register as register_cross_ref
from cd_mcp.tools.cultural_overlay import register as register_cultural_overlay
from cd_mcp.tools.debate_for_verse import register as register_debate_for_verse
from cd_mcp.tools.doctrinal_verdict import register as register_doctrinal_verdict
from cd_mcp.tools.evidence_inspect import register as register_evidence_inspect
from cd_mcp.tools.historical_inspect import register as register_historical_inspect
from cd_mcp.tools.lexical_lookup import register as register_lexical_lookup
from cd_mcp.tools.license_audit import register as register_license_audit
from cd_mcp.tools.parallel_translation import register as register_parallel_translation
from cd_mcp.tools.variant_inspect import register as register_variant_inspect
from cd_mcp.tools.versification_resolve import register as register_versification_resolve

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
        name="christian-doctrine",
        instructions=(
            "Manuscript-anchored biblical doctrine engine. START HERE: for any doctrinal "
            "question call doctrinal_verdict, which returns the verdict, key verses, and "
            "diagnostics in one call. The other tools (lexical_lookup, cross_ref, "
            "cultural_overlay, historical_inspect, etc.) are drill-downs for when you need "
            "more detail. Lexical verdicts derive from apparatus + interlinear + "
            "concordance only. Cultural overlay and historical attestation are diagnostic "
            "and never settle a verdict."
        ),
        lifespan=lifespan,
        # This is an internal service reached by other containers by name
        # (e.g. http://cd-mcp:8765). DNS-rebinding protection (a browser-origin
        # defence) would reject that Host header, so disable it here; access is
        # bounded by the private docker network instead.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
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
