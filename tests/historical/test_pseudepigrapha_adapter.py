"""Tests for the OT Pseudepigrapha adapter (ingest/historical/pseudepigrapha.py).

These tests run fully offline against cached upstream fixtures under
tests/historical/fixtures/ (one representative file per source format):

  - sacred-texts_boe004.htm        1 Enoch chapter I (sacred-texts BOE)
  - ccel_charles_jubilees_1.htm    Jubilees chapter 1 (CCEL per-chapter)
  - ecw_patriarchs-charles.html    all twelve Testaments (earlychristianwritings)

They exist to BREAK the adapter, not rubber-stamp it:
  - every parsed record MUST validate as a HistoricalChunk;
  - every anchor MUST match the per-work pattern in the schema;
  - 1 Enoch 1.9 (the verse Jude 14-15 cites) MUST be an atomic chunk and MUST
    keep Charles' ceiling brackets in text while dropping them from the
    embedding surface;
  - every Testaments chunk MUST carry contested_interpolation.type ==
    "recension-layer" with a note citing Charles, and chunks whose Charles text
    brackets an explicit Jesus-naming clause MUST redact it from text_to_embed;
  - normal (1 Enoch / Jubilees) chunks MUST be uncontested with NFC text and an
    embedding surface free of critical brackets;
  - parsing MUST be deterministic with no duplicate anchors.

No em-dashes or en-dashes anywhere in output.
"""

from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

import pytest

from ingest.historical import pseudepigrapha as adapter
from pipeline4.historical_schema import ANCHOR_PATTERNS, HistoricalChunk

FIXTURES = Path(__file__).parent / "fixtures"

_DASHES = (chr(0x2014), chr(0x2013))  # em-dash, en-dash (built so this file stays dash-clean)


@pytest.fixture(scope="module")
def staged_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Mirror the data/private/historical/pseudepigrapha layout from fixtures.

    The adapter's per-work parsers read a <root>/<work>/ directory of local
    files, so we lay the cached fixtures out under a temp root in exactly that
    shape and point the parsers at it. No network or real data/private access.
    """
    root = tmp_path_factory.mktemp("pseudepigrapha")
    (root / "1enoch").mkdir()
    (root / "jubilees").mkdir()
    (root / "test12").mkdir()
    shutil.copy(FIXTURES / "sacred-texts_boe004.htm", root / "1enoch" / "boe004.htm")
    shutil.copy(FIXTURES / "ccel_charles_jubilees_1.htm", root / "jubilees" / "1.htm")
    shutil.copy(
        FIXTURES / "ecw_patriarchs-charles.html",
        root / "test12" / "patriarchs-charles.html",
    )
    return root


@pytest.fixture(scope="module")
def enoch(staged_root: Path) -> list[HistoricalChunk]:
    return list(adapter._parse_enoch(staged_root / "1enoch"))


@pytest.fixture(scope="module")
def jubilees(staged_root: Path) -> list[HistoricalChunk]:
    return list(adapter._parse_jubilees(staged_root / "jubilees"))


@pytest.fixture(scope="module")
def test12(staged_root: Path) -> list[HistoricalChunk]:
    return list(adapter._parse_test12(staged_root / "test12"))


@pytest.fixture(scope="module")
def all_chunks(
    enoch: list[HistoricalChunk],
    jubilees: list[HistoricalChunk],
    test12: list[HistoricalChunk],
) -> list[HistoricalChunk]:
    return [*enoch, *jubilees, *test12]


# ---------------------------------------------------------------------------
# Contract: adapter shape
# ---------------------------------------------------------------------------


def test_source_slugs_declared() -> None:
    assert adapter.SOURCE_SLUGS == (
        "1enoch",
        "jubilees",
        "test12",
        "2baruch",
        "4ezra",
        "pssol",
        "sibor",
    )


def test_parse_is_callable() -> None:
    assert callable(adapter.parse)


# ---------------------------------------------------------------------------
# Each in-scope work yields chunks
# ---------------------------------------------------------------------------


def test_enoch_yields_chunks(enoch: list[HistoricalChunk]) -> None:
    assert enoch, "1 Enoch fixture produced zero chunks"


def test_jubilees_yields_chunks(jubilees: list[HistoricalChunk]) -> None:
    assert jubilees, "Jubilees fixture produced zero chunks"


def test_test12_yields_chunks(test12: list[HistoricalChunk]) -> None:
    # The single ECW page carries all twelve testaments.
    assert test12, "Testaments fixture produced zero chunks"
    patriarchs = {c.source.anchor_id.split(".")[1] for c in test12}
    assert patriarchs == set(adapter._T12_PATRIARCHS)


# ---------------------------------------------------------------------------
# All parsed records validate as HistoricalChunk
# ---------------------------------------------------------------------------


def test_all_records_validate(all_chunks: list[HistoricalChunk]) -> None:
    assert all_chunks
    for c in all_chunks:
        HistoricalChunk.model_validate(c.model_dump(mode="json"))


def test_all_records_fixed_metadata(all_chunks: list[HistoricalChunk]) -> None:
    for c in all_chunks:
        assert c.source_type == "second-temple-literature"
        assert c.source.author is None
        assert c.source.language == "en"
        assert c.source.translator == "R. H. Charles (1913)"
        assert c.license == "PD"
        assert c.redistribute is True
        assert c.chunk_id == c.source.anchor_id


def test_all_anchors_match_pattern(all_chunks: list[HistoricalChunk]) -> None:
    for c in all_chunks:
        slug = c.source.source_slug
        assert ANCHOR_PATTERNS[slug].match(c.source.anchor_id), c.source.anchor_id


# ---------------------------------------------------------------------------
# 1 Enoch 1.9 (Jude 14-15): atomic chunk, ceiling brackets handled
# ---------------------------------------------------------------------------


def test_enoch_one_nine_atomic(enoch: list[HistoricalChunk]) -> None:
    by_anchor = {c.chunk_id: c for c in enoch}
    e19 = by_anchor.get("1enoch.1.9")
    assert e19 is not None, "1enoch.1.9 (the Jude citation) was not emitted"
    assert "He cometh with ten thousands" in e19.text
    # Charles' critical ceiling brackets survive in text, not in the embedding.
    assert "⌈" in e19.text or "⌉" in e19.text
    assert "⌈" not in e19.text_to_embed
    assert "⌉" not in e19.text_to_embed


def test_enoch_normal_chunk_uncontested(enoch: list[HistoricalChunk]) -> None:
    for c in enoch:
        assert c.contested_interpolation.type == "none"
        assert c.contested_interpolation.note is None
        assert c.contested_interpolation.redact_for_embedding is False
        # NFC normalization holds.
        assert c.text == unicodedata.normalize("NFC", c.text)
        # Embedding surface carries no critical brackets.
        assert "⌈" not in c.text_to_embed
        assert "⌉" not in c.text_to_embed


def test_jubilees_chapter_granularity(jubilees: list[HistoricalChunk]) -> None:
    # Narrative prose: one chunk per chapter. The chapter-1 fixture is a single
    # chapter, so exactly one Jubilees chunk anchored at jubilees.1.1.
    assert len(jubilees) == 1
    c = jubilees[0]
    assert c.chunk_id == "jubilees.1.1"
    assert c.contested_interpolation.type == "none"
    assert c.text == c.text_to_embed
    # Verses joined and numbered so Charles' boundaries are recoverable.
    assert "1. And it came to pass" in c.text
    assert "2. And Moses went up" in c.text


# ---------------------------------------------------------------------------
# REQUIRED FLAG: Testaments are a Christianized recension
# ---------------------------------------------------------------------------


def test_test12_all_recension_layer(test12: list[HistoricalChunk]) -> None:
    assert test12
    for c in test12:
        ci = c.contested_interpolation
        assert ci.type == "recension-layer", c.chunk_id
        assert ci.note is not None
        assert "Charles" in ci.note
        assert "recension" in ci.note.lower()


def test_test12_jesus_naming_redacted(test12: list[HistoricalChunk]) -> None:
    redacted = [c for c in test12 if c.contested_interpolation.redact_for_embedding]
    assert redacted, "no Testaments chunk redacted a Jesus-naming clause"
    for c in redacted:
        # When redaction fires, the embedding surface must differ from text and
        # the bracketed Christian clause must be gone from the embedding.
        assert c.text != c.text_to_embed
        assert "Saviour of the world" not in c.text_to_embed
        assert "Lamb of God" not in c.text_to_embed


def test_test12_levi_christian_clause_present_in_text(
    test12: list[HistoricalChunk],
) -> None:
    # The Christian-recension clause stays verbatim in text for citation honesty
    # somewhere in the Testament of Levi material.
    levi_text = "\n".join(
        c.text for c in test12 if c.source.anchor_id.split(".")[1] == "levi"
    )
    assert "Saviour of the world" in levi_text


def test_test12_redaction_consistent_with_flag(test12: list[HistoricalChunk]) -> None:
    # If and only if redact_for_embedding is true, text and embedding differ.
    for c in test12:
        if c.contested_interpolation.redact_for_embedding:
            assert c.text != c.text_to_embed
        else:
            assert c.text == c.text_to_embed


# ---------------------------------------------------------------------------
# No em-dash / en-dash leaked into output text
# ---------------------------------------------------------------------------


def test_no_em_en_dashes_in_text(all_chunks: list[HistoricalChunk]) -> None:
    for c in all_chunks:
        for dash in _DASHES:
            assert dash not in c.text, f"dash in {c.chunk_id} text"
            assert dash not in c.text_to_embed, f"dash in {c.chunk_id} embed"


# ---------------------------------------------------------------------------
# Determinism and uniqueness
# ---------------------------------------------------------------------------


def test_deterministic_order(staged_root: Path) -> None:
    def run() -> list[str]:
        out = [
            *(c.chunk_id for c in adapter._parse_enoch(staged_root / "1enoch")),
            *(c.chunk_id for c in adapter._parse_jubilees(staged_root / "jubilees")),
            *(c.chunk_id for c in adapter._parse_test12(staged_root / "test12")),
        ]
        return out

    first = run()
    second = run()
    assert first == second
    assert len(first) == len(set(first)), "duplicate anchors in fixture parse"


def test_missing_work_dir_is_skipped(tmp_path: Path) -> None:
    # The three works without a clean Charles transcription (2baruch, 4ezra,
    # pssol) have no source directory; parse() must skip them silently.
    empty = tmp_path / "empty_root"
    empty.mkdir()
    # No <work> subdirectories: every per-work parser sees an absent dir.
    assert list(adapter._parse_enoch(empty / "1enoch")) == []
    assert list(adapter._parse_jubilees(empty / "jubilees")) == []
    assert list(adapter._parse_test12(empty / "test12")) == []
    assert list(adapter._parse_sibor(empty / "sibor")) == []
