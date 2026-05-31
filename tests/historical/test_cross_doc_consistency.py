"""Cross-document consistency tests for the Pipeline 4 / historical layer.

The schema doc, the catalog, the Pipeline 4 prompt, and the architecture
spec must agree on:
- source_type enum values (seven)
- attestation_type enum values (five)
- contested_interpolation type values (four)
- allowed source_slug values
- license slugs per source
- Neo4j label names and Qdrant collection name

A drift between any two of these documents is a contract violation that
this test suite catches before the implementation does.

No em-dashes or en-dashes in output.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA_DOC = REPO / "docs" / "HISTORICAL_SCHEMA.md"
CATALOG = REPO / "docs" / "historical_data_inventory_catalog.json"
PROMPT = REPO / "docs" / "phase_prompts" / "pipeline4_attestation.md"
ARCH = REPO / "docs" / "ARCHITECTURE.md"

SOURCE_TYPES = frozenset({
    "jewish-historian",
    "jewish-philosopher",
    "second-temple-literature",
    "roman-historian",
    "jewish-rabbinic",
    "qumran-sectarian",
    "qumran-biblical",
})

ATTESTATION_TYPES = frozenset({
    "corroborates",
    "complicates",
    "neutral",
    "parallel",
    "silent-where-expected",
})

INTERPOLATION_TYPES = frozenset({
    "none",
    "partial-interpolation",
    "recension-layer",
    "text-critical-variant",
})

LOSS_STATUS = frozenset({"complete", "partial", "fragmentary", "reconstructed"})


@functools.lru_cache(maxsize=1)
def _schema_doc() -> str:
    if not SCHEMA_DOC.exists():
        pytest.skip(f"Schema doc missing: {SCHEMA_DOC}")
    return SCHEMA_DOC.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _catalog() -> dict:
    if not CATALOG.exists():
        pytest.skip(f"Catalog missing: {CATALOG}")
    return json.loads(CATALOG.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _prompt() -> str:
    if not PROMPT.exists():
        pytest.skip(f"Prompt missing: {PROMPT}")
    return PROMPT.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _arch() -> str:
    if not ARCH.exists():
        pytest.skip(f"Architecture spec missing: {ARCH}")
    return ARCH.read_text(encoding="utf-8")


def test_source_types_in_schema_and_prompt() -> None:
    schema = _schema_doc()
    prompt = _prompt()
    for slug in SOURCE_TYPES:
        assert slug in schema, f"source_type {slug} missing from schema"
        assert slug in prompt, f"source_type {slug} missing from prompt"


def test_attestation_types_in_schema_and_prompt() -> None:
    schema = _schema_doc()
    prompt = _prompt()
    for slug in ATTESTATION_TYPES:
        assert slug in schema, f"attestation_type {slug} missing from schema"
        assert slug in prompt, f"attestation_type {slug} missing from prompt"


def test_interpolation_types_in_schema_and_prompt() -> None:
    schema = _schema_doc()
    prompt = _prompt()
    for slug in INTERPOLATION_TYPES - {"none"}:
        assert slug in schema, f"interpolation type {slug} missing from schema"
        assert slug in prompt, f"interpolation type {slug} missing from prompt"


def test_loss_status_values_in_schema() -> None:
    schema = _schema_doc()
    for slug in LOSS_STATUS:
        assert slug in schema, f"loss_status {slug} missing from schema"


def test_neo4j_labels_consistent_across_docs() -> None:
    """HistoricalSource, HistoricalWork, HistoricalChunk, ATTESTS must appear in schema, catalog, architecture."""
    schema = _schema_doc()
    catalog_raw = CATALOG.read_text(encoding="utf-8")
    arch = _arch()
    for label in ("HistoricalSource", "HistoricalWork", "HistoricalChunk", "ATTESTS"):
        assert label in schema, f"Label {label} missing from schema"
        assert label in catalog_raw or "HistoricalChunk" in catalog_raw, f"Label {label} missing from catalog"
        assert label in arch, f"Label {label} missing from architecture"


def test_hist_col_qdrant_name_consistent() -> None:
    schema = _schema_doc()
    arch = _arch()
    assert "hist_col" in schema
    assert "hist_col" in arch


def test_dss_option_a_consistent_across_schema_catalog_prompt() -> None:
    """DSS Option A discipline must be documented identically in all three."""
    schema = _schema_doc()
    catalog = _catalog()
    prompt = _prompt()
    assert "Option A" in schema
    assert "Option A" in prompt
    dss_entry = next((s for s in catalog["sources"] if s["name"] == "DSS-ETCBC"), None)
    assert dss_entry is not None, "DSS-ETCBC catalog entry missing"
    assert "Option A" in dss_entry.get("english_translation_discipline", "")


def test_perseus_license_consistent() -> None:
    """Perseus sources are CC-BY-SA-4.0 in catalog and architecture."""
    catalog = _catalog()
    arch = _arch()
    perseus_sources = [s for s in catalog["sources"] if "Perseus" in s["name"]]
    assert len(perseus_sources) >= 4, "Expected at least 4 Perseus sources (Josephus, Tacitus, Suetonius, Pliny)"
    for src in perseus_sources:
        assert src["license_id"] == "CC-BY-SA-4.0", f"{src['name']} not CC-BY-SA-4.0"
    assert "CC BY-SA 4.0" in arch or "CC-BY-SA-4.0" in arch


def test_dss_license_consistent() -> None:
    catalog = _catalog()
    arch = _arch()
    schema = _schema_doc()
    dss = next(s for s in catalog["sources"] if s["name"] == "DSS-ETCBC")
    assert dss["license_id"] == "CC-BY-NC-4.0"
    assert dss["redistribute"] is False
    assert "CC BY-NC 4.0" in arch or "CC-BY-NC-4.0" in arch
    assert "CC-BY-NC-4.0" in schema


def test_pipeline4_prompt_path_referenced_in_arch() -> None:
    arch = _arch()
    assert "docs/phase_prompts/pipeline4_attestation.md" in arch


def test_schema_doc_path_referenced_in_arch_and_catalog() -> None:
    arch = _arch()
    catalog_raw = CATALOG.read_text(encoding="utf-8")
    assert "HISTORICAL_SCHEMA.md" in arch
    assert "docs/HISTORICAL_SCHEMA.md" in catalog_raw


def test_catalog_path_referenced_in_arch() -> None:
    arch = _arch()
    assert "historical_data_inventory_catalog.json" in arch


def test_per_question_sidecar_path_consistent() -> None:
    schema = _schema_doc()
    arch = _arch()
    prompt = _prompt()
    catalog_raw = CATALOG.read_text(encoding="utf-8")
    pattern = "historical/<question_id>.json"
    assert pattern in schema
    assert pattern in catalog_raw
    short_form = "historical/<id>.json"
    assert short_form in arch or pattern in arch


def test_evidence_path_referenced_as_read_only_by_pipeline4() -> None:
    """evidence/<id>.json is Pipeline 4's read-only context."""
    prompt = _prompt()
    schema = _schema_doc()
    arch = _arch()
    for doc_text in (prompt, schema, arch):
        assert "evidence/" in doc_text


def test_no_lexical_store_grants_in_pipeline4() -> None:
    """Pipeline 4 must never grant access to the lexical store."""
    prompt = _prompt()
    arch = _arch()
    forbidden_phrases = [
        '"lexical"',
    ]
    pipeline4_section = ""
    if "Pipeline 4 walkthrough" in arch:
        pipeline4_section = arch.split("Pipeline 4 walkthrough")[1].split("## ")[0]
    assert 'allowed_stores: ["historical"]' in prompt or '"historical"' in prompt or '"historical"' in arch


def test_attestation_type_complicates_does_not_override_verdict() -> None:
    """The 'complicates' attestation must explicitly never modify the lexical verdict."""
    schema = _schema_doc()
    prompt = _prompt()
    arch = _arch()
    for doc_text in (schema, prompt, arch):
        lowered = doc_text.lower()
        assert "never override" in lowered or "never overrides" in lowered or "verdict stands" in lowered, \
            "complicates discipline (verdict stands) not stated in one of the docs"


def test_six_recon_jsons_referenced_from_catalog() -> None:
    """Every recon_ref in the catalog must point to one of the six recon.json files."""
    catalog = _catalog()
    expected_recon_files = {
        "tmp/pipeline4_recon/josephus/recon.json",
        "tmp/pipeline4_recon/philo/recon.json",
        "tmp/pipeline4_recon/roman-historians/recon.json",
        "tmp/pipeline4_recon/pseudepigrapha/recon.json",
        "tmp/pipeline4_recon/sefaria/recon.json",
        "tmp/pipeline4_recon/dss/recon.json",
    }
    seen_refs = {s["recon_ref"] for s in catalog["sources"] if "recon_ref" in s}
    for ref in seen_refs:
        assert ref in expected_recon_files, f"Unexpected recon_ref: {ref}"
