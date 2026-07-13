"""End-to-end cultural overlay smoke. Phase 06 Task 06.04."""

from __future__ import annotations

from cd_mcp.tools.cultural_overlay import CulturalOverlayInput
from cd_mcp.tools.cultural_overlay import handle as cultural_handle


def _chunk(tradition: str, source: str, license: str, redistribute: bool) -> dict:
    return {
        "tradition": tradition,
        "source": source,
        "stance": "affirms",
        "text": " ".join(["word"] * 200),
        "license": license,
        "redistribute": redistribute,
        "source_work_word_count": 200000,
    }


def test_cultural_overlay_returns_multiple_traditions() -> None:
    chunks = [
        _chunk("patristic", "CCEL-ANF", "public_domain", True),
        _chunk("catholic-magisterial", "Vatican.va-CCC", "©Libreria-Editrice-Vaticana", False),
        _chunk("lutheran", "BoC", "public_domain", True),
        _chunk("reformed", "opc.org-WCF", "public_domain", True),
        _chunk("eastern-orthodox", "oca.org-Hopko", "©OCA-Hopko-estate", False),
    ]
    env = cultural_handle(
        CulturalOverlayInput(doctrine="theology-proper", k=12),
        cultural_chunks=chunks,
    )
    traditions = {p["tradition"] for p in env["result"]["passages"]}
    assert len(traditions) >= 5


def test_cultural_overlay_nc_chunks_capped_at_100_words() -> None:
    chunks = [_chunk("catholic-magisterial", "CCC", "©x", False)]
    env = cultural_handle(CulturalOverlayInput(doctrine="theology-proper"), cultural_chunks=chunks)
    p = env["result"]["passages"][0]
    if p["snippet"] is not None:
        assert len(p["snippet"].split()) <= 100


def test_cultural_overlay_passages_are_cultural_only() -> None:
    chunks = [_chunk("reformed", "WCF", "public_domain", True)]
    env = cultural_handle(CulturalOverlayInput(doctrine="x"), cultural_chunks=chunks)
    for source in env["license_audit"]["sources_used"]:
        # No lexical-store source slugs allowed
        assert source["source"] not in {"MACULA-Greek", "MACULA-Hebrew", "STEPBible-TAGNT"}
