"""End-to-end variant-sensitivity smoke. Phase 06 Task 06.03."""

from __future__ import annotations

from cd_mcp.tools.parallel_translation import ParallelTranslationInput
from cd_mcp.tools.parallel_translation import handle as parallel_handle
from cd_mcp.tools.variant_inspect import VariantInspectInput
from cd_mcp.tools.variant_inspect import handle as variant_handle


def test_parallel_translation_multiple_translations() -> None:
    env = parallel_handle(
        ParallelTranslationInput(
            ref="John.1.18",
            translations=["ESV", "NASB", "NKJV", "NIV"],
            include_original=False,
        )
    )
    assert len(env["result"]["rows"]) == 4


def test_variant_inspect_v1_stub_returns_ecm_false() -> None:
    env = variant_handle(VariantInspectInput(ref="John.1.18"))
    assert env["result"]["ecm_published"] is False
    assert env["result"]["phase"] == "v1-deferred"


def test_variant_inspect_envelope_complete() -> None:
    env = variant_handle(VariantInspectInput(ref="John.1.18"))
    assert env["ok"] is True
    assert "license_audit" in env
    assert "trace_id" in env
