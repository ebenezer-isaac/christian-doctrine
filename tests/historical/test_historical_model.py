"""Tests for the Pipeline 4 Pydantic model (pipeline4/historical_schema.py).

Locks the fifteen validator rules in docs/HISTORICAL_SCHEMA.md "Validator
rules" plus the HistoricalChunk ingest record. These tests exist to BREAK the
model: each negative case proves a rule actually fires, not just that the happy
path parses.

No em-dashes or en-dashes in output.
"""

from __future__ import annotations

import copy

import pytest

from pipeline4.historical_schema import (
    HistoricalAttestation,
    HistoricalChunk,
    Witness,
)


# --------------------------------------------------------------------------
# Fixtures: minimal valid building blocks
# --------------------------------------------------------------------------


def _josephus_witness() -> dict:
    return {
        "witness_id": "josephus.ant.18.116",
        "source_type": "jewish-historian",
        "source": {
            "source_slug": "josephus",
            "work_id": "josephus.ant",
            "work_title": "Antiquities of the Jews",
            "author": "Flavius Josephus",
            "date_written_range": "93-94 CE",
            "anchor_id": "josephus.ant.18.116",
            "anchor_alt_citation": "Ant 18.5.2 (Whiston)",
            "language": "en",
            "translator": "William Whiston (1737)",
            "edition": "Perseus TEI tlg0526.tlg001.perseus-eng2",
        },
        "attestation_type": "complicates",
        "confidence": 0.85,
        "evidence_phrase": "some of the Jews thought the destruction of the army came from God",
        "rationale": "Josephus gives the political motive. Complementary, not contradictory.",
        "contested_interpolation": {"type": "none", "note": None, "redact_for_embedding": False},
        "provenance": {
            "original_language": "el",
            "witness_chain": ["greek-niese", "english-whiston-1737"],
            "extant_witnesses": ["MSS A, M, V, W per Niese"],
            "loss_status": "complete",
        },
        "text": "Now some of the Jews thought the destruction of the army came from God.",
        "text_to_embed": "Now some of the Jews thought the destruction of the army came from God.",
        "license": "CC-BY-SA-4.0",
        "redistribute": True,
        "license_note": "Perseus TEI CC-BY-SA-4.0.",
    }


def _attestation(witnesses: list[dict], present: bool, summary: str) -> dict:
    used = [
        {"source_slug": w["source"]["source_slug"], "license": w["license"], "redistribute": w["redistribute"]}
        for w in witnesses
    ]
    safe = all(w["redistribute"] for w in witnesses) if witnesses else True
    return {
        "$schema_version": "1.0",
        "id": "doc-john-the-baptist-death",
        "question_id": "doc-john-the-baptist-death",
        "generated_at": "2026-06-04T00:00:00Z",
        "pipeline_version": "v1",
        "model": "claude-opus-4-7",
        "attestation_present": present,
        "witnesses": witnesses,
        "summary": summary,
        "license_audit": {
            "sources_used": used,
            "evidence_safe_to_publish": safe,
            "non_redistributable_reason": None if safe else "Cites a non-redistributable source.",
        },
        "flags": [],
    }


# --------------------------------------------------------------------------
# Happy paths
# --------------------------------------------------------------------------


def test_empty_attestation_validates() -> None:
    doc = _attestation([], present=False, summary="")
    m = HistoricalAttestation.model_validate(doc)
    assert m.attestation_present is False
    assert m.witnesses == []


def test_full_attestation_validates() -> None:
    doc = _attestation([_josephus_witness()], present=True, summary=" ".join(["word"] * 60))
    m = HistoricalAttestation.model_validate(doc)
    assert len(m.witnesses) == 1
    assert m.schema_version == "1.0"


def test_schema_version_alias_roundtrips() -> None:
    doc = _attestation([], present=False, summary="")
    m = HistoricalAttestation.model_validate(doc)
    dumped = m.model_dump(by_alias=True)
    assert dumped["$schema_version"] == "1.0"


def test_dss_qumran_anchor_and_nc_license() -> None:
    w = _josephus_witness()
    w.update(
        witness_id="1qs.col04.line03",
        source_type="qumran-sectarian",
        attestation_type="parallel",
        license="CC-BY-NC-4.0",
        redistribute=False,
        license_note=None,
    )
    w["source"].update(
        source_slug="1qs",
        work_id="1qs",
        work_title="Community Rule",
        author=None,
        anchor_id="1qs.col04.line03",
        language="hbo",
        translator=None,
        edition="ETCBC dss .tf",
    )
    w["provenance"] = {
        "original_language": "hbo",
        "witness_chain": ["qumran-cave-1"],
        "extant_witnesses": ["1QS"],
        "loss_status": "complete",
    }
    doc = _attestation([w], present=True, summary=" ".join(["word"] * 55))
    m = HistoricalAttestation.model_validate(doc)
    assert m.recompute_evidence_safe_to_publish() is False


# --------------------------------------------------------------------------
# Negative cases: each rule must fire
# --------------------------------------------------------------------------


def test_rule1_id_must_equal_question_id() -> None:
    doc = _attestation([], present=False, summary="")
    doc["id"] = "doc-other"
    with pytest.raises(ValueError):
        HistoricalAttestation.model_validate(doc)


def test_rule3_present_true_requires_witnesses() -> None:
    doc = _attestation([], present=True, summary=" ".join(["word"] * 60))
    with pytest.raises(ValueError):
        HistoricalAttestation.model_validate(doc)


def test_rule3_present_false_forbids_witnesses() -> None:
    doc = _attestation([_josephus_witness()], present=False, summary="")
    with pytest.raises(ValueError):
        HistoricalAttestation.model_validate(doc)


def test_rule6_bad_anchor_rejected() -> None:
    doc = _attestation([_josephus_witness()], present=True, summary=" ".join(["w"] * 60))
    doc["witnesses"][0]["source"]["anchor_id"] = "josephus.ant.18"
    doc["witnesses"][0]["witness_id"] = "josephus.ant.18"
    with pytest.raises(ValueError):
        HistoricalAttestation.model_validate(doc)


def test_rule8_evidence_phrase_word_cap() -> None:
    w = _josephus_witness()
    w["evidence_phrase"] = " ".join(["word"] * 61)
    with pytest.raises(ValueError):
        Witness.model_validate(w)


def test_rule9_contested_note_required() -> None:
    w = _josephus_witness()
    w["contested_interpolation"] = {"type": "partial-interpolation", "note": None, "redact_for_embedding": True}
    w["text_to_embed"] = "redacted form differs"
    with pytest.raises(ValueError):
        Witness.model_validate(w)


def test_rule10_redact_requires_divergent_embed_text() -> None:
    w = _josephus_witness()
    w["contested_interpolation"] = {
        "type": "partial-interpolation",
        "note": "Testimonium Flavianum clause bracketed.",
        "redact_for_embedding": True,
    }
    # text_to_embed still equals text -> inconsistent
    with pytest.raises(ValueError):
        Witness.model_validate(w)


def test_rule11_witness_chain_non_empty() -> None:
    w = _josephus_witness()
    w["provenance"]["witness_chain"] = []
    with pytest.raises(ValueError):
        Witness.model_validate(w)


def test_rule13_redistribute_must_match_registry() -> None:
    w = _josephus_witness()
    w["redistribute"] = False  # CC-BY-SA-4.0 must be True
    with pytest.raises(ValueError):
        Witness.model_validate(w)


def test_rule13_unregistered_license_rejected() -> None:
    w = _josephus_witness()
    w["license"] = "GPL-3.0"
    with pytest.raises(ValueError):
        Witness.model_validate(w)


def test_rule14_summary_too_short_when_present() -> None:
    doc = _attestation([_josephus_witness()], present=True, summary="too short")
    with pytest.raises(ValueError):
        HistoricalAttestation.model_validate(doc)


def test_rule15_no_em_dash_in_summary() -> None:
    doc = _attestation([_josephus_witness()], present=True, summary="word " * 30 + "— dash")
    with pytest.raises(ValueError):
        HistoricalAttestation.model_validate(doc)


def test_rule15_no_en_dash_in_rationale() -> None:
    w = _josephus_witness()
    w["rationale"] = "Has an en–dash in it which is forbidden by the discipline rule here."
    with pytest.raises(ValueError):
        Witness.model_validate(w)


def test_duplicate_witness_id_rejected() -> None:
    doc = _attestation([_josephus_witness(), _josephus_witness()], present=True, summary="word " * 60)
    with pytest.raises(ValueError):
        HistoricalAttestation.model_validate(doc)


def test_extra_field_forbidden() -> None:
    doc = _attestation([], present=False, summary="")
    doc["unexpected_key"] = "boom"
    with pytest.raises(ValueError):
        HistoricalAttestation.model_validate(doc)


# --------------------------------------------------------------------------
# HistoricalChunk ingest record
# --------------------------------------------------------------------------


def test_historical_chunk_ingest_record() -> None:
    chunk = {
        "chunk_id": "josephus.ant.18.116",
        "source_type": "jewish-historian",
        "source": _josephus_witness()["source"],
        "contested_interpolation": {"type": "none", "note": None, "redact_for_embedding": False},
        "provenance": _josephus_witness()["provenance"],
        "text": "Now some of the Jews thought the destruction came from God.",
        "text_to_embed": "Now some of the Jews thought the destruction came from God.",
        "license": "CC-BY-SA-4.0",
        "redistribute": True,
        "license_note": None,
    }
    m = HistoricalChunk.model_validate(chunk)
    assert m.chunk_id == "josephus.ant.18.116"


def test_historical_chunk_bad_anchor_rejected() -> None:
    chunk = {
        "chunk_id": "x",
        "source_type": "jewish-historian",
        "source": {**_josephus_witness()["source"], "anchor_id": "not-valid"},
        "contested_interpolation": {"type": "none", "note": None, "redact_for_embedding": False},
        "provenance": _josephus_witness()["provenance"],
        "text": "t",
        "text_to_embed": "t",
        "license": "CC-BY-SA-4.0",
        "redistribute": True,
        "license_note": None,
    }
    with pytest.raises(ValueError):
        HistoricalChunk.model_validate(chunk)
