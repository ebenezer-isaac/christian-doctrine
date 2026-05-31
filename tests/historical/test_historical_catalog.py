"""Tests for docs/historical_data_inventory_catalog.json schema contract.

Verifies the catalog against the H.0 pre-ingest blueprint contract.
The catalog is loaded at test run time. Asserts top-level shape,
per-source shape, scope coverage, deadend coverage, and the no-em-dash
rule on free-text fields.

The H.0 catalog is intentionally pre-ingest; sample_indices and
sampling_stride_proof are absent and land in a later H.1 architect
commit. These tests do not require those.

No em-dashes or en-dashes in output or file content.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO / "docs" / "historical_data_inventory_catalog.json"


@functools.lru_cache(maxsize=1)
def _load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.exists():
        pytest.skip(f"Catalog file not found: {CATALOG_PATH}")
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_file_parses() -> None:
    catalog = _load_catalog()
    assert isinstance(catalog, dict)


def test_top_level_keys_present() -> None:
    catalog = _load_catalog()
    required = {
        "$schema_version", "$mirrors", "generated_at", "phase",
        "$catalog_intent", "scope", "sampling_method", "record_model",
        "historical_vs_cultural_note", "explicit_deadends", "sources",
        "post_ingest_obligations",
    }
    missing = required - set(catalog.keys())
    assert not missing, f"Missing top-level keys: {missing}"


def test_schema_version_is_pre_ingest() -> None:
    catalog = _load_catalog()
    assert catalog["$schema_version"] == "v1-pre-ingest"
    assert "H.0" in catalog["phase"]


def test_scope_in_scope_historical_nonempty() -> None:
    catalog = _load_catalog()
    in_scope = catalog["scope"]["in_scope_historical"]
    assert isinstance(in_scope, list)
    assert len(in_scope) >= 8, f"Expected at least 8 in-scope sources, found {len(in_scope)}"


def test_scope_explicit_deadends_carries_evidence() -> None:
    """Every deadend must have a reason and an evidence_url per architecture rule."""
    catalog = _load_catalog()
    deadends = catalog["scope"]["explicit_deadends"]
    assert len(deadends) >= 6, f"Expected at least 6 deadends, found {len(deadends)}"
    for dd in deadends:
        assert "name" in dd, f"Deadend missing name: {dd}"
        assert "reason" in dd, f"Deadend missing reason: {dd['name']}"
        assert "evidence_url" in dd, f"Deadend missing evidence_url: {dd['name']}"
        assert dd["reason"], f"Deadend has empty reason: {dd['name']}"


def test_known_deadends_present() -> None:
    """The recon-surfaced deadends must be in the catalog."""
    catalog = _load_catalog()
    deadend_names = {dd["name"] for dd in catalog["scope"]["explicit_deadends"]}
    required = {
        "Talmud-Bavli",
        "Talmud-Yerushalmi",
        "OCP-source-language-witnesses",
        "Philo-Cohn-Wendland-Greek",
        "IAA-Leon-Levy-DSS-images",
        "Wise-Abegg-Cook-DSS-English",
    }
    missing = required - deadend_names
    assert not missing, f"Required deadends missing: {missing}"


def test_sources_list_shape() -> None:
    catalog = _load_catalog()
    sources = catalog["sources"]
    assert isinstance(sources, list)
    assert len(sources) >= 8, f"Expected at least 8 sources, found {len(sources)}"
    for src in sources:
        assert isinstance(src, dict)


def test_each_source_has_required_metadata() -> None:
    catalog = _load_catalog()
    base_required = {"name", "layer", "redistribute", "root_path", "recon_verdict", "recon_ref"}
    for src in catalog["sources"]:
        missing = base_required - set(src.keys())
        assert not missing, f"Source {src.get('name', '?')} missing keys: {missing}"
        license_keys = {k for k in src.keys() if k.startswith("license_id")}
        assert license_keys, f"Source {src['name']} missing any license_id* field"


def test_each_source_layer_is_seven() -> None:
    """All historical sources sit at Layer 7 (historical sibling track)."""
    catalog = _load_catalog()
    for src in catalog["sources"]:
        assert src["layer"] == 7, f"Source {src['name']} not at Layer 7"


def test_recon_verdicts_valid() -> None:
    catalog = _load_catalog()
    allowed = {"GREEN", "YELLOW", "RED"}
    for src in catalog["sources"]:
        verdict = src["recon_verdict"]
        tokens = verdict.split() if verdict else []
        head = tokens[1] if tokens and tokens[0] == "Inferred" else (tokens[0] if tokens else "")
        assert head in allowed, f"Source {src['name']} has invalid recon_verdict: {verdict}"


def test_recon_refs_point_to_existing_files() -> None:
    """Every recon_ref must resolve to an actual recon.json on disk."""
    catalog = _load_catalog()
    seen_refs = set()
    for src in catalog["sources"]:
        ref = src["recon_ref"]
        ref_path = REPO / ref
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        assert ref_path.exists(), f"Source {src['name']}: recon_ref does not exist: {ref_path}"


def test_each_source_has_expected_chunks_estimate() -> None:
    """Every source must declare an expected chunk count under one of the chunks fields."""
    catalog = _load_catalog()
    chunk_field_keys = {
        "expected_chunks_total",
        "expected_chunks_total_christian_relevant_only",
    }
    for src in catalog["sources"]:
        has_chunks = any(k in src for k in chunk_field_keys)
        assert has_chunks, f"Source {src['name']} missing expected_chunks_* field"


def test_license_id_values_are_known() -> None:
    catalog = _load_catalog()
    allowed_license_ids = {
        "CC-BY-SA-4.0", "CC-BY-NC-4.0", "CC-BY-4.0", "CC-BY", "CC0",
        "public_domain", "PD",
    }
    for src in catalog["sources"]:
        if "license_id" in src:
            assert src["license_id"] in allowed_license_ids, (
                f"Source {src['name']} has unknown license_id: {src['license_id']}"
            )


def test_dss_carries_redistribute_false() -> None:
    """ETCBC/dss is CC-BY-NC-4.0; redistribute must be false."""
    catalog = _load_catalog()
    dss = next((s for s in catalog["sources"] if s["name"] == "DSS-ETCBC"), None)
    assert dss is not None, "DSS-ETCBC source entry missing"
    assert dss["license_id"] == "CC-BY-NC-4.0"
    assert dss["redistribute"] is False
    assert "Option A" in dss.get("english_translation_discipline", "")


def test_perseus_sources_carry_share_alike() -> None:
    """Perseus sources (Josephus, Tacitus, Suetonius, Pliny) are CC-BY-SA-4.0."""
    catalog = _load_catalog()
    perseus_names = {
        "Josephus-Perseus", "Tacitus-Annals-Perseus",
        "Suetonius-Twelve-Caesars-Perseus", "Pliny-Letters-Perseus",
    }
    for src in catalog["sources"]:
        if src["name"] in perseus_names:
            assert src["license_id"] == "CC-BY-SA-4.0", (
                f"Perseus source {src['name']} expected CC-BY-SA-4.0, got {src['license_id']}"
            )


def test_post_ingest_obligations_h_steps_documented() -> None:
    catalog = _load_catalog()
    obligations = catalog["post_ingest_obligations"]
    for h_step in ("h1_procurement_completeness", "h4_count_contract",
                    "h5_snapshot_determinism", "h6_adapter_purity", "fixture_capture"):
        assert h_step in obligations, f"Post-ingest obligation {h_step} missing"


def test_record_model_attributes_match_schema() -> None:
    catalog = _load_catalog()
    attrs = catalog["record_model"]["attributes"]
    required = {
        "chunk_id", "source_type",
        "source.source_slug", "source.work_id",
        "attestation_type", "confidence", "evidence_phrase",
        "contested_interpolation.type",
        "provenance.witness_chain",
        "text", "text_to_embed", "license", "redistribute",
    }
    missing = required - set(attrs)
    assert not missing, f"record_model.attributes missing: {missing}"


def test_no_em_or_en_dashes_in_catalog() -> None:
    """Feedback rule: no em-dash or en-dash in free-text fields."""
    raw = CATALOG_PATH.read_text(encoding="utf-8")
    assert "—" not in raw, "Em-dash U+2014 present in catalog"
    assert "–" not in raw, "En-dash U+2013 present in catalog"


def test_scope_in_scope_aligns_with_sources_list() -> None:
    """Every scope.in_scope_historical entry must have a corresponding sources[] entry."""
    catalog = _load_catalog()
    in_scope = set(catalog["scope"]["in_scope_historical"])
    source_names = {s["name"] for s in catalog["sources"]}
    missing = in_scope - source_names
    assert not missing, f"in_scope_historical entries not in sources[]: {missing}"


def test_catalog_intent_states_pre_ingest_nature() -> None:
    catalog = _load_catalog()
    intent = catalog["$catalog_intent"]
    assert "pre-ingest" in intent.lower() or "blueprint" in intent.lower()
    assert "sampling_stride_proof" in intent or "sample_indices" in intent
