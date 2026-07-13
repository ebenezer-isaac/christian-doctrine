"""variant_inspect: CBGM variants. v1 returns ecm_published: false (CBGM deferred)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from cd_mcp.tools._common import ToolInputBase, success_envelope

TOOL_NAME = "variant_inspect"


class VariantInspectInput(ToolInputBase):
    ref: str = Field(min_length=1)
    include_witnesses: bool = True
    phase: str | None = None


def handle(payload: VariantInspectInput) -> dict[str, Any]:
    result = {
        "ref": payload.ref,
        "ecm_published": False,
        "phase": payload.phase or "v1-deferred",
        "variant_units": [],
        "note": "CBGM is deferred from v1. ECM published shadow only.",
    }
    sources = [{"source": "INTF-NTVMR", "license": "CC-BY-4.0"}]
    return success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources,
        caller_context=payload.caller_context,
    )


def register(server: Any) -> None:
    @server.tool(name=TOOL_NAME, description="Variant readings (v1 stub; CBGM deferred).")
    def _tool(
        ref: str,
        include_witnesses: bool = True,
        phase: str | None = None,
        caller_context: Literal["personal", "public-share", "export"] = "personal",
    ) -> dict[str, Any]:
        payload = VariantInspectInput(
            ref=ref,
            include_witnesses=include_witnesses,
            phase=phase,
            caller_context=caller_context,
        )
        return handle(payload)
