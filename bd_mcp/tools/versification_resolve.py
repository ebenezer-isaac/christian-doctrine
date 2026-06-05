"""versification_resolve: TVTMS-backed verse-numbering bridge."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from bd_mcp.runtime import app_context
from bd_mcp.tools._common import ToolInputBase, success_envelope
from ingest.versification_mapper import VersificationMapper

TOOL_NAME = "versification_resolve"


class VersificationResolveInput(ToolInputBase):
    ref: str = Field(min_length=1)
    from_scheme: str = Field(min_length=1)
    to_scheme: str = Field(min_length=1)


def handle(
    payload: VersificationResolveInput,
    mapper: VersificationMapper | None = None,
) -> dict[str, Any]:
    mapper = mapper or VersificationMapper()
    resolved = mapper.resolve(payload.ref, payload.from_scheme, payload.to_scheme)
    all_mappings = [
        resolved,
        {
            "from_scheme": payload.to_scheme,
            "from_ref": resolved["to_ref"],
            "to_scheme": payload.from_scheme,
            "to_ref": resolved["from_ref"],
            "rule_type": resolved["rule_type"],
            "block_scope": resolved["block_scope"],
        },
    ]
    result = {
        "from_ref": resolved["from_ref"],
        "from_scheme": resolved["from_scheme"],
        "to_ref": resolved["to_ref"],
        "to_scheme": resolved["to_scheme"],
        "rule_type": resolved["rule_type"],
        "all_mappings": all_mappings,
    }
    sources = [{"source": "STEPBible-TVTMS", "license": "CC-BY-4.0"}]
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(
        name=TOOL_NAME, description="Resolve a verse reference between versification schemes."
    )
    def _tool(
        ctx: Context,
        ref: str,
        from_scheme: str,
        to_scheme: str,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = VersificationResolveInput(
            ref=ref,
            from_scheme=from_scheme,
            to_scheme=to_scheme,
            caller_context=caller_context,
        )
        return handle(payload, mapper=app_context(ctx).mapper)
