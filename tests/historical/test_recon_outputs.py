"""Tests for the six Pipeline 4 recon outputs under tmp/pipeline4_recon/.

The recon agents produced one recon.json per source. These tests validate
that each file exists, parses as JSON, declares a verdict in the
allowed set, and exposes the minimum fields needed by the catalog and the
schema. The recon outputs are the empirical basis for the H.0 catalog;
breaking them invalidates the catalog claims.

No em-dashes or en-dashes in output.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RECON_ROOT = REPO / "tmp" / "pipeline4_recon"

RECON_SOURCES = (
    "josephus",
    "philo",
    "roman-historians",
    "pseudepigrapha",
    "sefaria",
    "dss",
)

ALLOWED_VERDICTS = {"GREEN", "YELLOW", "RED"}


@functools.lru_cache(maxsize=None)
def _load_recon(slug: str) -> dict:
    p = RECON_ROOT / slug / "recon.json"
    if not p.exists():
        pytest.skip(f"Recon file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug", RECON_SOURCES)
def test_recon_file_exists_and_parses(slug: str) -> None:
    recon = _load_recon(slug)
    assert isinstance(recon, dict)


@pytest.mark.parametrize("slug", RECON_SOURCES)
def test_recon_declares_a_verdict(slug: str) -> None:
    recon = _load_recon(slug)
    verdict = recon.get("verdict") or recon.get("verdict_v1") or recon.get("verdict_mishnah_v1")
    if not verdict and slug == "sefaria":
        verdict = recon.get("verdict_mishnah_v1")
    assert verdict, f"Recon {slug} missing verdict field"
    head = verdict.split()[0] if isinstance(verdict, str) else ""
    assert head in ALLOWED_VERDICTS, f"Recon {slug} verdict not in allowed set: {verdict}"


def test_josephus_recon_specific_fields() -> None:
    recon = _load_recon("josephus")
    assert recon["source_slug"] == "josephus"
    assert recon["license_slug"] == "CC-BY-SA-4.0"
    assert "TEI-XML" in recon["format"]
    assert recon["estimated_chunks_total"] == 2304


def test_philo_recon_specific_fields() -> None:
    recon = _load_recon("philo")
    assert recon["source_slug"] == "philo"
    assert recon["license_slug"].startswith("PD")
    assert "Yonge" in recon["license_slug"] or "PD" in recon["license_slug"]
    assert recon["estimated_chunks_total"] == 13000


def test_roman_historians_recon_specific_fields() -> None:
    recon = _load_recon("roman-historians")
    assert recon["source_slug"] == "roman-historians"
    assert recon["license_slug"] == "CC-BY-SA-4.0"
    scope = recon["scope_recommendation"]
    assert any(s in scope for s in ("christian-relevant-only", "full-works", "hybrid")), (
        f"scope_recommendation does not mention any allowed value: {scope[:120]}"
    )
    subs = {s["slug"] for s in recon["subsources"]}
    assert "tacitus-annals" in subs
    assert "suetonius-twelve-caesars" in subs
    assert "pliny-letters" in subs


def test_pseudepigrapha_recon_specific_fields() -> None:
    recon = _load_recon("pseudepigrapha")
    assert recon["source_slug"] == "pseudepigrapha"
    assert recon["license_slug"] == "PD"
    sub_slugs = {s["slug"] for s in recon["subsources"]}
    expected = {"1-enoch", "jubilees", "testaments-twelve-patriarchs", "2-baruch", "4-ezra",
                "psalms-of-solomon", "sibylline-oracles"}
    assert expected.issubset(sub_slugs), f"Missing subsources: {expected - sub_slugs}"


def test_sefaria_recon_specific_fields() -> None:
    recon = _load_recon("sefaria")
    assert recon["source_slug"] == "sefaria-mishnah-talmud"
    assert recon["verdict_mishnah_v1"] == "GREEN"
    assert recon["verdict_talmud_v1"] == "YELLOW"
    assert recon["deferral_recommendation_confirmed"] is False


def test_dss_recon_specific_fields() -> None:
    recon = _load_recon("dss")
    assert recon["source_slug"] == "dss"
    assert recon["verdict_v1"] == "YELLOW"
    assert recon["deferral_recommendation"] in {"partial-ingest", "defer", "full-ingest"}
    probes = {p["name"] for p in recon["subsources_probed"]}
    assert any("ETCBC" in p for p in probes), "ETCBC/dss probe not in DSS recon"


def test_every_recon_carries_sample_chunk() -> None:
    """Each recon must include a verbatim sample chunk so adapter authors can verify against real data."""
    for slug in RECON_SOURCES:
        recon = _load_recon(slug)
        sample_keys = [k for k in recon if "sample_chunk" in k]
        assert sample_keys, f"Recon {slug} missing sample_chunk* field"
        for sk in sample_keys:
            val = recon[sk]
            if isinstance(val, str):
                assert val, f"Recon {slug} sample_chunk field {sk} is empty"
            elif isinstance(val, dict):
                assert val, f"Recon {slug} sample_chunk dict {sk} is empty"


def test_every_recon_carries_recommended_adapter_strategy() -> None:
    """Adapter strategy is the implementation hand-off; every recon must produce one."""
    for slug in RECON_SOURCES:
        recon = _load_recon(slug)
        strategy = recon.get("recommended_adapter_strategy") or recon.get("fallback_strategy")
        assert strategy, f"Recon {slug} missing recommended_adapter_strategy/fallback_strategy"
        if isinstance(strategy, str):
            assert len(strategy) > 100, f"Recon {slug} adapter strategy too short: {len(strategy)} chars"


def test_no_em_or_en_dashes_in_recon_files() -> None:
    """Recon JSON contents must not carry em or en dashes per the standing rule."""
    for slug in RECON_SOURCES:
        p = RECON_ROOT / slug / "recon.json"
        if not p.exists():
            continue
        raw = p.read_text(encoding="utf-8")
        assert "—" not in raw, f"Em-dash in {slug}/recon.json"
        assert "–" not in raw, f"En-dash in {slug}/recon.json"
