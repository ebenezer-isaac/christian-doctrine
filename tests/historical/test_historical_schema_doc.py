"""Tests for docs/HISTORICAL_SCHEMA.md structural contract.

The schema doc is the authoritative spec for the historical-attestation
sidecar layer (Pipeline 4). These tests lock in the contract before the
Pydantic model and adapters land: the enums, anchor patterns, allowed
source slugs, and per-section invariants must be present and consistent.

No em-dashes or en-dashes in output or file content.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA_DOC_PATH = REPO / "docs" / "HISTORICAL_SCHEMA.md"


@functools.lru_cache(maxsize=1)
def _load_doc() -> str:
    if not SCHEMA_DOC_PATH.exists():
        pytest.skip(f"Schema doc not found: {SCHEMA_DOC_PATH}")
    return SCHEMA_DOC_PATH.read_text(encoding="utf-8")


def test_schema_doc_exists() -> None:
    assert SCHEMA_DOC_PATH.exists(), f"Schema doc missing: {SCHEMA_DOC_PATH}"


def test_schema_version_declared() -> None:
    doc = _load_doc()
    assert "# Historical Attestation Schema v1.0" in doc
    assert '"$schema_version": "1.0"' in doc or "schema_version: 1.0" in doc


def test_seven_source_types_listed() -> None:
    """The seven source_type enum values must be documented."""
    doc = _load_doc()
    required_slugs = {
        "jewish-historian",
        "jewish-philosopher",
        "second-temple-literature",
        "roman-historian",
        "jewish-rabbinic",
        "qumran-sectarian",
        "qumran-biblical",
    }
    for slug in required_slugs:
        assert f"`{slug}`" in doc, f"source_type {slug} not listed"


def test_five_attestation_types_listed() -> None:
    """The five attestation_type enum values must be documented."""
    doc = _load_doc()
    required = {"corroborates", "complicates", "neutral", "parallel", "silent-where-expected"}
    for slug in required:
        assert f"`{slug}`" in doc, f"attestation_type {slug} not listed"


def test_four_interpolation_types_listed() -> None:
    """The four contested_interpolation.type values must be documented."""
    doc = _load_doc()
    required = {"none", "partial-interpolation", "recension-layer", "text-critical-variant"}
    for slug in required:
        assert f"`{slug}`" in doc, f"contested_interpolation type {slug} not listed"


def test_four_loss_status_values_listed() -> None:
    """provenance.loss_status enum: complete, partial, fragmentary, reconstructed."""
    doc = _load_doc()
    required = {"complete", "partial", "fragmentary", "reconstructed"}
    for slug in required:
        assert slug in doc, f"loss_status {slug} not listed"


def test_allowed_source_slugs_documented() -> None:
    """The allowed source_slug list must include the v1 sources."""
    doc = _load_doc()
    required = {
        "josephus", "philo",
        "1enoch", "jubilees", "test12", "2baruch", "4ezra", "pssol", "sibor",
        "tacitus", "suetonius", "pliny",
        "mishnah",
        "1qs", "1qm", "1qha", "1qphab", "cd", "11q19",
    }
    for slug in required:
        assert slug in doc, f"source_slug {slug} not documented"


def test_anchor_patterns_documented() -> None:
    """The per-source anchor patterns must be specified."""
    doc = _load_doc()
    expected_patterns = [
        "josephus.<work>.<book>.<niese_section>",
        "philo.<treatise-slug>.<cohn-wendland-paragraph>",
        "tacitus.annals.<book>.<chapter>",
        "suetonius.<life>.<chapter>",
        "pliny.ep.<book>.<letter>",
        "mishnah.<tractate>.<chapter>.<mishnah>",
    ]
    for pattern in expected_patterns:
        assert pattern in doc, f"anchor pattern {pattern} not documented"


def test_neo4j_node_labels_present() -> None:
    """The four Neo4j labels for the historical store must be documented."""
    doc = _load_doc()
    for label in ("HistoricalSource", "HistoricalWork", "HistoricalChunk", "ATTESTS"):
        assert label in doc, f"Neo4j label {label} not documented"


def test_qdrant_collection_named() -> None:
    doc = _load_doc()
    assert "hist_col" in doc, "Qdrant historical collection name hist_col not documented"


def test_pipeline4_dispatch_contract_present() -> None:
    """The Pipeline 4 dispatch contract section must be present."""
    doc = _load_doc()
    assert "Pipeline 4 dispatch contract" in doc
    assert 'allowed_stores' in doc
    assert 'forbidden_stores' in doc


def test_dss_option_a_discipline_documented() -> None:
    """DSS Option A (transliteration only, no engine-authored gloss) must be locked."""
    doc = _load_doc()
    assert "Option A" in doc
    assert "ETCBC" in doc
    assert "transliteration" in doc.lower()


def test_triangle_test_section_present() -> None:
    doc = _load_doc()
    assert "Triangle test" in doc or "triangle test" in doc
    assert "+/- 0.05" in doc or "0.05" in doc, "Triangle confidence tolerance not stated"


def test_evidence_phrase_word_cap_stated() -> None:
    """evidence_phrase has a 60-word cap (vs cultural's 30-word cap)."""
    doc = _load_doc()
    assert "60 words" in doc, "60-word evidence_phrase cap not documented"


def test_extra_forbid_referenced() -> None:
    """Pydantic extra=forbid discipline must be stated."""
    doc = _load_doc()
    assert 'extra="forbid"' in doc or "extra=forbid" in doc


def test_summary_word_cap_stated() -> None:
    """summary is 50-300 words when attestation_present is true."""
    doc = _load_doc()
    assert "50-300 words" in doc or "50 to 300 words" in doc


def test_what_is_not_in_schema_section_present() -> None:
    doc = _load_doc()
    assert "What is NOT in this schema" in doc
    assert "verdict" in doc.lower(), "schema must forbid witness-level verdict field"


def test_validator_rules_enumerated() -> None:
    """The validator rules list must enumerate at least 12 rules."""
    doc = _load_doc()
    validator_section = doc.split("## Validator rules")[1] if "## Validator rules" in doc else ""
    assert validator_section, "Validator rules section missing"
    numbered_rules = re.findall(r"^\d+\. ", validator_section, re.MULTILINE)
    assert len(numbered_rules) >= 12, f"Expected at least 12 validator rules, found {len(numbered_rules)}"


def test_no_em_or_en_dashes() -> None:
    """Feedback rule: no em-dash (U+2014) or en-dash (U+2013) anywhere."""
    doc = _load_doc()
    assert "—" not in doc, "Em-dash U+2014 present in HISTORICAL_SCHEMA.md"
    assert "–" not in doc, "En-dash U+2013 present in HISTORICAL_SCHEMA.md"


def test_authoritative_layer_disclaimer_present() -> None:
    """Historical attestation is diagnostic, NEVER overrides lexical verdict."""
    doc = _load_doc()
    lowered = doc.lower()
    assert "never override" in lowered or "never overrides" in lowered or "diagnostic" in lowered
    assert "lexical verdict" in lowered


def test_per_question_sidecar_path_documented() -> None:
    doc = _load_doc()
    assert "historical/<question_id>.json" in doc
