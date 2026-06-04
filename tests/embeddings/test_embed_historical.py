"""Unit tests for embeddings.embed_historical (verifier-z1 caste).

These exercise the PURE pieces of the historical embedder WITHOUT any live
Voyage or Qdrant connection:

* the hist_col payload matches the docs/HISTORICAL_SCHEMA.md key set exactly;
* the redistribute-safe ``text`` gate persists ``text_to_embed`` for a
  CC-BY-NC-4.0 (redistribute=false) chunk and verbatim ``text`` for a PD
  (redistribute=true) chunk (fail-closed copyright contract);
* a chunk with empty/whitespace ``text_to_embed`` is skipped, never sent to
  Voyage, and counted in ``skipped_no_text``;
* the point id is deterministic (``uuid5(NS, chunk_id)``).

Test chunks are built through ``pipeline4.historical_schema.HistoricalChunk``
so every fixture is schema-valid (extra=forbid, anchor/license/dash rules all
enforced), not a hand-rolled dict that could drift from the contract.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from embeddings import embed_historical
from embeddings.embed_historical import NS, VOYAGE_OUTPUT_DIMENSION
from pipeline4.historical_schema import HistoricalChunk


# --------------------------------------------------------------------------
# Fixtures: schema-valid chunks via HistoricalChunk, dumped to the JSONL dict
# shape embed_historical reads (model_dump(mode="json")).
# --------------------------------------------------------------------------

_FIXED_VECTOR = [0.01] * VOYAGE_OUTPUT_DIMENSION


def _pd_chunk(chunk_id: str = "josephus.ant.18.63", text_to_embed: str = "") -> dict[str, Any]:
    """A public-domain Josephus chunk (redistribute=true, gate OPEN)."""
    verbatim = "Now there was about this time Jesus, a wise man."
    chunk = HistoricalChunk(
        chunk_id=chunk_id,
        source_type="jewish-historian",
        source={
            "source_slug": "josephus",
            "work_id": "josephus.antiquities",
            "work_title": "Antiquities of the Jews",
            "author": "Flavius Josephus",
            "date_written_range": "93-94 CE",
            "anchor_id": "josephus.ant.18.63",
            "anchor_alt_citation": "Ant. 18.3.3",
            "language": "en",
            "translator": "William Whiston",
            "edition": "Whiston 1737",
        },
        contested_interpolation={
            "type": "partial-interpolation",
            "note": "The Testimonium Flavianum carries a contested Christian gloss.",
            "redact_for_embedding": False,
        },
        provenance={
            "original_language": "grc",
            "witness_chain": ["Eusebius", "Greek MSS"],
            "extant_witnesses": ["Codex Ambrosianus"],
            "loss_status": "complete",
        },
        text=verbatim,
        text_to_embed=verbatim,
        license="PD",
        redistribute=True,
        license_note=None,
    )
    return chunk.model_dump(mode="json")


def _ncnd_chunk(chunk_id: str = "1qs.col04.line03", text_to_embed: str = "") -> dict[str, Any]:
    """A CC-BY-NC-4.0 Qumran chunk (redistribute=false, gate CLOSED).

    Option A: text_to_embed == text (the DSS transliteration), so the gate
    closing falls back to text_to_embed but the surface is preserved.
    """
    surface = "transliterated community-rule passage on the two spirits"
    chunk = HistoricalChunk(
        chunk_id=chunk_id,
        source_type="qumran-sectarian",
        source={
            "source_slug": "1qs",
            "work_id": "1qs.community-rule",
            "work_title": "Community Rule",
            "author": None,
            "date_written_range": "100 BCE",
            "anchor_id": "1qs.col04.line03",
            "anchor_alt_citation": None,
            "language": "hbo",
            "translator": None,
            "edition": "DSS Electronic Library",
        },
        contested_interpolation={
            "type": "none",
            "note": None,
            "redact_for_embedding": False,
        },
        provenance={
            "original_language": "hbo",
            "witness_chain": ["1QS"],
            "extant_witnesses": ["1QS"],
            "loss_status": "partial",
        },
        text=surface,
        text_to_embed=surface,
        license="CC-BY-NC-4.0",
        redistribute=False,
        license_note=None,
    )
    return chunk.model_dump(mode="json")


# --------------------------------------------------------------------------
# Fakes: capture upserts, return a fixed vector, never touch the network.
# --------------------------------------------------------------------------


class _FakeVoyage:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def embed(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        n = len(kwargs["texts"])

        class _Result:
            embeddings = [list(_FIXED_VECTOR) for _ in range(n)]

        return _Result()


class _FakeQdrant:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.created: list[str] = []
        self.deleted: list[str] = []

    def upsert(self, collection_name: str, points: Any) -> None:
        self.upserts.append({"collection": collection_name, "points": list(points)})

    def get_collections(self) -> Any:
        class _C:
            collections: list[Any] = []

        return _C()

    def create_collection(self, collection_name: str, **kwargs: Any) -> None:
        self.created.append(collection_name)

    def delete_collection(self, collection_name: str) -> None:
        self.deleted.append(collection_name)


def _write_jsonl(tmp_path: Path, chunks: list[dict[str, Any]]) -> Path:
    import json

    p = tmp_path / "hist.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    return p


# --------------------------------------------------------------------------
# _point_for: payload schema + license gate + deterministic id
# --------------------------------------------------------------------------

_EXPECTED_PAYLOAD_KEYS = {
    "chunk_id",
    "source_slug",
    "source_type",
    "work_id",
    "anchor_id",
    "doctrine_coarse_list",
    "doctrine_fine_list",
    "attestation_per_doctrine",
    "contested_interpolation_type",
    "language",
    "license",
    "redistribute",
    "text",
}


def test_payload_keys_match_hist_col_schema() -> None:
    point = embed_historical._point_for(_pd_chunk(), _FIXED_VECTOR)
    assert set(point.payload.keys()) == _EXPECTED_PAYLOAD_KEYS


def test_payload_field_values_for_pd_chunk() -> None:
    point = embed_historical._point_for(_pd_chunk(), _FIXED_VECTOR)
    p = point.payload
    assert p["chunk_id"] == "josephus.ant.18.63"
    assert p["source_slug"] == "josephus"
    assert p["source_type"] == "jewish-historian"
    assert p["work_id"] == "josephus.antiquities"
    assert p["anchor_id"] == "josephus.ant.18.63"
    assert p["language"] == "en"
    assert p["license"] == "PD"
    assert p["redistribute"] is True
    assert p["contested_interpolation_type"] == "partial-interpolation"


def test_v1_doctrine_fields_seeded_empty() -> None:
    point = embed_historical._point_for(_pd_chunk(), _FIXED_VECTOR)
    p = point.payload
    assert p["doctrine_coarse_list"] == []
    assert p["doctrine_fine_list"] == []
    assert p["attestation_per_doctrine"] == {}


def test_gate_open_pd_persists_verbatim_text() -> None:
    chunk = _pd_chunk()
    point = embed_historical._point_for(chunk, _FIXED_VECTOR)
    assert point.payload["text"] == chunk["text"]
    assert point.payload["text"] == "Now there was about this time Jesus, a wise man."


def test_gate_closed_ncnd_persists_text_to_embed() -> None:
    chunk = _ncnd_chunk()
    point = embed_historical._point_for(chunk, _FIXED_VECTOR)
    # CC-BY-NC-4.0 denies bulk -> fall back to text_to_embed, never verbatim.
    assert point.payload["text"] == chunk["text_to_embed"]
    assert point.payload["redistribute"] is False


def test_gate_fail_closed_on_unknown_license() -> None:
    # An unrecognized license must NOT leak verbatim text. We bypass schema
    # validation here on purpose: the gate is the last line of defense even
    # for a malformed/forged chunk dict that never went through HistoricalChunk.
    chunk = {
        "chunk_id": "x.1.1",
        "source_type": "jewish-historian",
        "source": {
            "source_slug": "josephus",
            "work_id": "w",
            "anchor_id": "a",
            "language": "en",
        },
        "contested_interpolation": {"type": "none"},
        "text": "VERBATIM SECRET",
        "text_to_embed": "safe surface",
        "license": "©Some-Proprietary-Press",
        "redistribute": False,
    }
    point = embed_historical._point_for(chunk, _FIXED_VECTOR)
    assert point.payload["text"] == "safe surface"
    assert "VERBATIM SECRET" not in point.payload["text"]


def test_point_id_deterministic_uuid5() -> None:
    chunk = _pd_chunk()
    point = embed_historical._point_for(chunk, _FIXED_VECTOR)
    expected = str(uuid.uuid5(NS, chunk["chunk_id"]))
    assert point.id == expected
    # And stable across calls.
    again = embed_historical._point_for(chunk, _FIXED_VECTOR)
    assert again.id == expected


def test_point_vector_is_named_dense_2048() -> None:
    point = embed_historical._point_for(_pd_chunk(), _FIXED_VECTOR)
    assert set(point.vector.keys()) == {"dense"}
    assert len(point.vector["dense"]) == VOYAGE_OUTPUT_DIMENSION


# --------------------------------------------------------------------------
# embed_file: empty-text skip, batching, no empty strings to Voyage
# --------------------------------------------------------------------------


def test_empty_text_to_embed_is_skipped(tmp_path: Path) -> None:
    good = _pd_chunk()
    blank = _pd_chunk(chunk_id="josephus.ant.18.64")
    # Force a blank text_to_embed on the dict (post-validation) to simulate a
    # textless leaf without tripping the min_length=1 schema rule.
    blank["text_to_embed"] = "   "
    path = _write_jsonl(tmp_path, [good, blank])
    voyage = _FakeVoyage()
    qdrant = _FakeQdrant()

    counts = embed_historical.embed_file(path, qdrant, voyage, "hist_col")

    assert counts["embedded"] == 1
    assert counts["skipped_no_text"] == 1
    assert counts["failures"] == 0


def test_no_empty_string_ever_sent_to_voyage(tmp_path: Path) -> None:
    good = _pd_chunk()
    blank = _pd_chunk(chunk_id="josephus.ant.18.65")
    blank["text_to_embed"] = ""
    path = _write_jsonl(tmp_path, [good, blank])
    voyage = _FakeVoyage()
    qdrant = _FakeQdrant()

    embed_historical.embed_file(path, qdrant, voyage, "hist_col")

    for call in voyage.calls:
        for t in call["texts"]:
            assert t.strip() != ""


def test_embed_file_upserts_to_target_collection(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path, [_pd_chunk(), _ncnd_chunk()])
    voyage = _FakeVoyage()
    qdrant = _FakeQdrant()

    counts = embed_historical.embed_file(path, qdrant, voyage, "hist_col")

    assert counts["embedded"] == 2
    assert qdrant.upserts, "expected at least one upsert"
    for u in qdrant.upserts:
        assert u["collection"] == "hist_col"
    # Voyage called with input_type=document at the right dimension.
    for call in voyage.calls:
        assert call["input_type"] == "document"
        assert call["output_dimension"] == VOYAGE_OUTPUT_DIMENSION


def test_voyage_input_type_is_document(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path, [_pd_chunk()])
    voyage = _FakeVoyage()
    qdrant = _FakeQdrant()
    embed_historical.embed_file(path, qdrant, voyage, "hist_col")
    assert voyage.calls
    assert all(c["input_type"] == "document" for c in voyage.calls)


# --------------------------------------------------------------------------
# _recreate_collection: drop-once, named dense vector, scoped to collection
# --------------------------------------------------------------------------


def test_recreate_collection_creates_named_dense_vector() -> None:
    qdrant = _FakeQdrant()
    embed_historical._recreate_collection(qdrant, "hist_col")
    assert qdrant.created == ["hist_col"]
    # Nothing existed, so nothing deleted.
    assert qdrant.deleted == []


def test_recreate_collection_drops_existing_then_recreates() -> None:
    class _FakeQdrantWithExisting(_FakeQdrant):
        def get_collections(self) -> Any:
            class _Named:
                name = "hist_col"

            class _C:
                collections = [_Named()]

            return _C()

    qdrant = _FakeQdrantWithExisting()
    embed_historical._recreate_collection(qdrant, "hist_col")
    assert qdrant.deleted == ["hist_col"]
    assert qdrant.created == ["hist_col"]
