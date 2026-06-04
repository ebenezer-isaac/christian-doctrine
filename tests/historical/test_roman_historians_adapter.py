"""Tests for the Roman-historian adapters.

Two adapters are exercised:
  * ingest/historical/roman_historians.py (Tacitus P4 milestone slicer,
    Suetonius + Pliny P5 EpiDoc walker), and
  * ingest/historical/pliny_melmoth.py (Melmoth 1746 English Pliny).

Fixtures under tests/historical/fixtures/ keep the suite offline:
  * perseus_phi1351_phi005_perseus-lat1.xml : Tacitus Annals book 15, ch 42-46
    only (trimmed P4 TEI; preserves the 15.44 Christianos passage).
  * perseus_phi1348_abo015_perseus-lat2.xml : Suetonius Divus Claudius (full
    P5 EpiDoc Life; small file, exercises chapter > section nesting at 25.4).
  * pliny_ep_10_melmoth.txt : staged Melmoth letters Ep 10.96 and 10.97.

These tests are written to BREAK the adapters, not rubber-stamp them:
  - the christian-relevant anchors MUST parse to the exact expected anchor_ids;
  - Tacitus 15.44 MUST carry the text-critical-variant flag and name Pilatum;
  - every parsed record MUST validate as a HistoricalChunk;
  - the Pliny English chunks MUST share anchor_id with the Latin chunks while
    keeping a distinct chunk_id (the join contract);
  - parsing MUST be deterministic.

No em-dashes or en-dashes in output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.historical import pliny_melmoth, roman_historians
from pipeline4.historical_schema import ANCHOR_PATTERNS, HistoricalChunk

FIXTURES = Path(__file__).parent / "fixtures"

_TACITUS_FIXTURE = FIXTURES / "perseus_phi1351_phi005_perseus-lat1.xml"
_SUETONIUS_DIR = FIXTURES  # flat layout: phi1348.abo015.perseus-lat2.xml lives here
_MELMOTH_FIXTURE = FIXTURES / "pliny_ep_10_melmoth.txt"


# ---------------------------------------------------------------------------
# Fixture-driven parse helpers (offline; pure functions over fixture paths)
# ---------------------------------------------------------------------------


def _tacitus_chunks() -> list[HistoricalChunk]:
    return list(roman_historians._parse_tacitus(_TACITUS_FIXTURE))


def _suetonius_chunks() -> list[HistoricalChunk]:
    # Both Claudius (abo015) and Nero (abo016) EpiDoc fixtures ship under the
    # flat fixtures dir; the adapter resolves both via the flat-layout fallback.
    return list(roman_historians._parse_suetonius(_SUETONIUS_DIR))


def _melmoth_chunks() -> list[HistoricalChunk]:
    return list(pliny_melmoth.parse(_MELMOTH_FIXTURE))


@pytest.fixture(scope="module")
def tacitus() -> list[HistoricalChunk]:
    return _tacitus_chunks()


@pytest.fixture(scope="module")
def melmoth() -> list[HistoricalChunk]:
    return _melmoth_chunks()


# ---------------------------------------------------------------------------
# Adapter contract
# ---------------------------------------------------------------------------


def test_source_slugs_declared() -> None:
    assert roman_historians.SOURCE_SLUGS == ("tacitus", "suetonius", "pliny")
    assert pliny_melmoth.SOURCE_SLUGS == ("pliny",)


def test_parse_callable() -> None:
    assert callable(roman_historians.parse)
    assert callable(pliny_melmoth.parse)


# ---------------------------------------------------------------------------
# Tacitus: christian-relevant anchors parse and 15.44 carries the variant flag
# ---------------------------------------------------------------------------


def test_tacitus_anchors_parse(tacitus: list[HistoricalChunk]) -> None:
    anchors = [c.source.anchor_id for c in tacitus]
    assert anchors == [
        "tacitus.annals.15.43",
        "tacitus.annals.15.44",
        "tacitus.annals.15.45",
    ]


def test_tacitus_anchor_pattern(tacitus: list[HistoricalChunk]) -> None:
    pat = ANCHOR_PATTERNS["tacitus"]
    for c in tacitus:
        assert pat.match(c.source.anchor_id)


def test_tacitus_1544_variant_flag(tacitus: list[HistoricalChunk]) -> None:
    by_anchor = {c.source.anchor_id: c for c in tacitus}
    c = by_anchor["tacitus.annals.15.44"]
    ci = c.contested_interpolation
    assert ci.type == "text-critical-variant"
    assert ci.redact_for_embedding is False
    assert ci.note is not None
    assert "Christianos" in ci.note
    assert "Chrestianos" in ci.note
    assert "Fisher" in ci.note
    # The verbatim passage names Christ and Pilate; text == text_to_embed (no
    # span removed since redact_for_embedding is False).
    assert "Christianos" in c.text
    assert "Pontium Pilatum" in c.text
    assert c.text == c.text_to_embed


def test_tacitus_neighbors_uncontested(tacitus: list[HistoricalChunk]) -> None:
    by_anchor = {c.source.anchor_id: c for c in tacitus}
    for a in ("tacitus.annals.15.43", "tacitus.annals.15.45"):
        ci = by_anchor[a].contested_interpolation
        assert ci.type == "none"
        assert ci.note is None
        assert ci.redact_for_embedding is False


def test_tacitus_loss_status_partial(tacitus: list[HistoricalChunk]) -> None:
    for c in tacitus:
        assert c.provenance.loss_status == "partial"


def test_tacitus_chapter_text_isolated(tacitus: list[HistoricalChunk]) -> None:
    # The milestone slicer must not bleed chapter 45 prose into chapter 44.
    by_anchor = {c.source.anchor_id: c for c in tacitus}
    c44 = by_anchor["tacitus.annals.15.44"]
    c45 = by_anchor["tacitus.annals.15.45"]
    # 15.45 opens "Interea conferendis pecuniis pervastata Italia"; that phrase
    # must be in 45, not 44.
    assert "conferendis pecuniis" in c45.text
    assert "conferendis pecuniis" not in c44.text


def test_tacitus_markup_stripped(tacitus: list[HistoricalChunk]) -> None:
    for c in tacitus:
        assert "<" not in c.text
        assert "milestone" not in c.text
        assert "&" not in c.text  # entities decoded/dropped


# ---------------------------------------------------------------------------
# Suetonius EpiDoc path (Claudius fixture)
# ---------------------------------------------------------------------------


def test_suetonius_claudius_sections() -> None:
    chunks = _suetonius_chunks()
    by_anchor = {c.source.anchor_id: c for c in chunks}
    # Claudius 25.3/4/5 must be present (Nero fixture not shipped).
    for sec in ("3", "4", "5"):
        assert f"suetonius.claudius.25.{sec}" in by_anchor
    c = by_anchor["suetonius.claudius.25.4"]
    # The Chresto sentence is the christian-relevant attestation.
    assert "Chresto" in c.text
    assert "Iudaeos" in c.text
    assert c.source.source_slug == "suetonius"
    assert c.source_type == "roman-historian"
    assert ANCHOR_PATTERNS["suetonius"].match(c.source.anchor_id)
    assert c.provenance.loss_status == "complete"


def test_suetonius_section_isolated() -> None:
    chunks = _suetonius_chunks()
    by_anchor = {c.source.anchor_id: c for c in chunks}
    # 25.4 (Chresto) text must not bleed into 25.3 or 25.5.
    assert "Chresto" not in by_anchor["suetonius.claudius.25.3"].text
    assert "Chresto" not in by_anchor["suetonius.claudius.25.5"].text


# ---------------------------------------------------------------------------
# Pliny English (Melmoth) joins Latin on anchor_id
# ---------------------------------------------------------------------------


def test_melmoth_two_chunks(melmoth: list[HistoricalChunk]) -> None:
    assert len(melmoth) == 2
    anchors = [c.source.anchor_id for c in melmoth]
    assert anchors == ["pliny.ep.10.96", "pliny.ep.10.97"]


def test_melmoth_metadata(melmoth: list[HistoricalChunk]) -> None:
    for c in melmoth:
        assert c.source.source_slug == "pliny"
        assert c.source_type == "roman-historian"
        assert c.source.language == "en"
        assert c.source.translator == "William Melmoth (1746)"
        assert c.license == "PD"
        assert c.redistribute is True
        assert c.provenance.original_language == "la"
        assert ANCHOR_PATTERNS["pliny"].match(c.source.anchor_id)


def test_melmoth_chunk_id_distinct_from_latin(
    melmoth: list[HistoricalChunk],
) -> None:
    # English chunk_id uses the .en suffix; the Latin adapter uses .la.
    for c in melmoth:
        assert c.chunk_id.endswith(".en")
        assert c.chunk_id != c.source.anchor_id
        # The Latin chunk for the same anchor would be roman_historians.<anchor>.la
        latin_chunk_id = f"roman_historians.{c.source.anchor_id}.la"
        assert c.chunk_id != latin_chunk_id


def test_pliny_english_joins_latin_on_anchor() -> None:
    # The join contract: English (Melmoth) and Latin (Perseus) chunks for the
    # christian-relevant letters share anchor_id while keeping distinct chunk_id.
    en = {c.source.anchor_id: c for c in _melmoth_chunks()}
    la = {
        c.source.anchor_id: c
        for c in roman_historians._parse_pliny(
            roman_historians._PLINY_FILE
        )
        if c.source.anchor_id in ("pliny.ep.10.96", "pliny.ep.10.97")
    }
    for anchor in ("pliny.ep.10.96", "pliny.ep.10.97"):
        assert anchor in en, f"English chunk missing for {anchor}"
        assert anchor in la, f"Latin chunk missing for {anchor}"
        en_c, la_c = en[anchor], la[anchor]
        # Same join key, different chunk_id, different language.
        assert en_c.source.anchor_id == la_c.source.anchor_id
        assert en_c.chunk_id != la_c.chunk_id
        assert en_c.source.language == "en"
        assert la_c.source.language == "la"


def test_melmoth_content(melmoth: list[HistoricalChunk]) -> None:
    by_anchor = {c.source.anchor_id: c for c in melmoth}
    # Pliny's letter to Trajan.
    p = by_anchor["pliny.ep.10.96"]
    assert "Christian" in p.text
    assert "invariable rule" in p.text
    assert "[" not in p.text  # footnote markers stripped
    # Trajan's reply.
    t = by_anchor["pliny.ep.10.97"]
    assert "right course" in t.text
    assert "Anonymous information" in t.text


def test_melmoth_header_line_removed(melmoth: list[HistoricalChunk]) -> None:
    for c in melmoth:
        assert "TO THE EMPEROR TRAJAN" not in c.text
        assert "TRAJAN TO PLINY" not in c.text


# ---------------------------------------------------------------------------
# Validity and determinism
# ---------------------------------------------------------------------------


def test_all_records_validate() -> None:
    chunks = _tacitus_chunks() + _suetonius_chunks() + _melmoth_chunks()
    assert chunks
    for c in chunks:
        # Round-trip through the model to prove every record is schema-clean.
        HistoricalChunk.model_validate(c.model_dump(mode="json"))
        assert c.text and c.text_to_embed


def test_text_equals_embed_when_uncontested() -> None:
    chunks = _tacitus_chunks() + _suetonius_chunks() + _melmoth_chunks()
    for c in chunks:
        if c.contested_interpolation.type == "none":
            assert c.text == c.text_to_embed


def test_deterministic_order() -> None:
    first = [c.chunk_id for c in _tacitus_chunks()]
    second = [c.chunk_id for c in _tacitus_chunks()]
    assert first == second
    m1 = [c.chunk_id for c in _melmoth_chunks()]
    m2 = [c.chunk_id for c in _melmoth_chunks()]
    assert m1 == m2


def test_no_duplicate_chunk_ids() -> None:
    chunks = (
        list(roman_historians.parse()) + list(pliny_melmoth.parse())
    )
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), "duplicate chunk_id across adapters"


def test_full_staged_parse_counts() -> None:
    # Integration over the real staged data/private corpus (not fixtures).
    roman = list(roman_historians.parse())
    melmoth = list(pliny_melmoth.parse())
    # Tacitus 3 + Suetonius 5 (Nero 16 has only sections 1-2) + Pliny 3 = 11.
    assert len(roman) == 11, [c.source.anchor_id for c in roman]
    assert len(melmoth) == 2
