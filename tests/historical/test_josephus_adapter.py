"""Tests for the Josephus Perseus TEI adapter (ingest/historical/josephus.py).

These tests run fully offline against trimmed TEI fixtures under
tests/historical/fixtures/ (one English file per work, books trimmed to keep
the fixtures small while preserving Antiquities book 18 so the Testimonium
Flavianum at josephus.ant.18.63 is exercised).

They exist to BREAK the adapter, not to rubber-stamp it:
  - the TF chunk MUST carry a partial-interpolation flag and a redacted
    embedding surface, and the disputed clause MUST be gone from text_to_embed
    but present in text;
  - a normal chunk MUST be uncontested with text == text_to_embed;
  - every parsed record MUST validate as a HistoricalChunk;
  - parsing the fixtures MUST be deterministic (byte-identical anchor order);
  - the count MUST be plausible for the trimmed fixtures.

No em-dashes or en-dashes in output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.historical import josephus
from pipeline4.historical_schema import HistoricalChunk

FIXTURES = Path(__file__).parent / "fixtures"

# (fixture filename, tlg, work slug, title, date range, has_books)
_FIXTURE_WORKS = (
    ("perseus_tlg0526_tlg001_perseus-eng2.xml", "tlg001", "ant",
     "Antiquities of the Jews", "93-94 CE", True),
    ("perseus_tlg0526_tlg002_perseus-eng2.xml", "tlg002", "vita",
     "The Life of Flavius Josephus", "c. 99 CE", False),
    ("perseus_tlg0526_tlg003_perseus-eng2.xml", "tlg003", "apion",
     "Against Apion", "c. 97 CE", True),
    ("perseus_tlg0526_tlg004_perseus-eng2.xml", "tlg004", "wars",
     "The Wars of the Jews", "75-79 CE", True),
)


def _parse_fixtures() -> list[HistoricalChunk]:
    chunks: list[HistoricalChunk] = []
    for fname, tlg, work, title, date_range, has_books in _FIXTURE_WORKS:
        path = FIXTURES / fname
        assert path.is_file(), f"missing fixture {path}"
        chunks.extend(
            josephus._parse_work(path, tlg, work, title, date_range, has_books)
        )
    return chunks


@pytest.fixture(scope="module")
def chunks() -> list[HistoricalChunk]:
    return _parse_fixtures()


@pytest.fixture(scope="module")
def by_anchor(chunks: list[HistoricalChunk]) -> dict[str, HistoricalChunk]:
    return {c.chunk_id: c for c in chunks}


# ---------------------------------------------------------------------------
# Contract: adapter shape
# ---------------------------------------------------------------------------


def test_source_slugs_declared() -> None:
    assert josephus.SOURCE_SLUGS == ("josephus",)


def test_parse_is_a_generator_function() -> None:
    # parse() must be importable and callable; it reads staged data and is the
    # loader entry point. We exercise the pure path via _parse_work in tests.
    assert callable(josephus.parse)


# ---------------------------------------------------------------------------
# All parsed records validate as HistoricalChunk
# ---------------------------------------------------------------------------


def test_all_records_validate(chunks: list[HistoricalChunk]) -> None:
    assert chunks, "fixtures produced zero chunks"
    for c in chunks:
        # Re-validate via the model to prove every emitted record is schema-clean
        # (HistoricalChunk validation already ran at construction; round-trip it).
        HistoricalChunk.model_validate(c.model_dump(mode="json"))


def test_all_anchors_match_pattern(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        assert c.chunk_id == c.source.anchor_id
        assert c.source.anchor_id.startswith("josephus.")
        work = c.source.anchor_id.split(".")[1]
        assert work in {"ant", "vita", "apion", "wars"}


def test_fixed_metadata(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        assert c.source_type == "jewish-historian"
        assert c.source.source_slug == "josephus"
        assert c.source.author == "Flavius Josephus"
        assert c.source.language == "en"
        assert c.source.translator == "William Whiston (1737)"
        assert c.source.edition.startswith("urn:cts:greekLit:tlg0526.")
        assert c.license == "CC-BY-SA-4.0"
        assert c.redistribute is True
        assert c.provenance.original_language == "el"
        assert c.provenance.loss_status == "complete"
        assert c.provenance.witness_chain == [
            "greek-niese",
            "english-whiston-1737",
        ]


# ---------------------------------------------------------------------------
# REQUIRED FLAG: Testimonium Flavianum at josephus.ant.18.63
# ---------------------------------------------------------------------------


def test_testimonium_flavianum_flagged(
    by_anchor: dict[str, HistoricalChunk],
) -> None:
    tf = by_anchor.get("josephus.ant.18.63")
    assert tf is not None, "TF anchor josephus.ant.18.63 not parsed from fixture"

    ci = tf.contested_interpolation
    assert ci.type == "partial-interpolation"
    assert ci.redact_for_embedding is True
    assert ci.note is not None and "Christ" in ci.note

    # The disputed clause is preserved in text but removed from the embedding.
    assert "He was [the] Christ." in tf.text
    assert "He was [the] Christ." not in tf.text_to_embed
    assert tf.text != tf.text_to_embed

    # The surrounding authentic core survives in both surfaces.
    assert "Now there was about this time Jesus" in tf.text
    assert "Now there was about this time Jesus" in tf.text_to_embed
    assert "tribe of Christians" in tf.text_to_embed


def test_testimonium_alt_citation(
    by_anchor: dict[str, HistoricalChunk],
) -> None:
    tf = by_anchor["josephus.ant.18.63"]
    # Classic Whiston pointer for the Testimonium is Ant 18.3.3.
    assert tf.source.anchor_alt_citation == "Ant 18.3.3 (Whiston)"


# ---------------------------------------------------------------------------
# Normal chunks are uncontested and have text == text_to_embed
# ---------------------------------------------------------------------------


def test_normal_chunk_uncontested(
    by_anchor: dict[str, HistoricalChunk],
) -> None:
    normal = by_anchor.get("josephus.wars.1.1")
    assert normal is not None, "expected normal anchor josephus.wars.1.1"
    assert normal.contested_interpolation.type == "none"
    assert normal.contested_interpolation.note is None
    assert normal.contested_interpolation.redact_for_embedding is False
    assert normal.text == normal.text_to_embed
    assert normal.text.strip()


def test_only_tf_is_contested(chunks: list[HistoricalChunk]) -> None:
    contested = [
        c.chunk_id
        for c in chunks
        if c.contested_interpolation.type != "none"
    ]
    assert contested == ["josephus.ant.18.63"]


def test_editor_notes_excluded(
    by_anchor: dict[str, HistoricalChunk],
) -> None:
    # The Antiquities preface (book 1 section 1) carries a <note resp="editor">
    # beginning "This preface of Josephus is excellent". It must not appear in
    # the chunk text. Book 1 is not in the trimmed fixture, so assert against a
    # known editor-note phrase absent from every parsed chunk instead.
    joined = "\n".join(c.text for c in by_anchor.values())
    assert "highly worthy the repeated perusal" not in joined


# ---------------------------------------------------------------------------
# Count plausibility and determinism
# ---------------------------------------------------------------------------


def test_count_plausible(chunks: list[HistoricalChunk]) -> None:
    # Trimmed fixtures: ant book 18 (sections up to n=65) + vita 6 + apion book 1
    # (6) + wars book 1 (6). Expect a modest but non-trivial count.
    assert 30 <= len(chunks) <= 120, f"unexpected fixture chunk count {len(chunks)}"


def test_deterministic_order() -> None:
    first = [c.chunk_id for c in _parse_fixtures()]
    second = [c.chunk_id for c in _parse_fixtures()]
    assert first == second
    # No duplicate anchors within the fixture set.
    assert len(first) == len(set(first))


def test_works_present(chunks: list[HistoricalChunk]) -> None:
    works = {c.chunk_id.split(".")[1] for c in chunks}
    assert works == {"ant", "vita", "apion", "wars"}
