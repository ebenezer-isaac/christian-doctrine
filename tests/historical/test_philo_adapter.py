"""Tests for the Philo Yonge adapter (ingest/historical/philo.py).

These tests run fully offline against three representative Yonge treatise pages
staged under tests/historical/fixtures/:

  - yonge_book01.html  : De Opificio (On the Creation). A flat "(N)" treatise.
  - yonge_book25.html  : De Vita Mosis II (On the Life of Moses, II). A flat
                         "(N)" treatise whose slug carries an explicit Roman
                         ordinal (-ii) to avoid the I/II collision.
  - yonge_book40.html  : Legatio ad Gaium (On the Embassy to Gaius). A large flat
                         "(N)" treatise that contains the "( 292)" internal-space
                         typo, so it exercises the marker-tolerance path.

They exist to BREAK the adapter, not to rubber-stamp it:
  - every parsed record MUST validate as a HistoricalChunk;
  - every anchor MUST match ANCHOR_PATTERNS["philo"];
  - the bookN -> treatise-slug mapping MUST hold for the fixture books;
  - editorial apparatus ({*}, {**...}, {#ref}, numeric {12}, (#ref)) MUST NOT
    leak into chunk text, and no em-dash or en-dash may appear;
  - paragraph anchors MUST be a gap-free 1..N sequence per fixture treatise;
  - parsing MUST be deterministic (byte-identical anchor order) with no dup
    anchors;
  - the 45-row treatise-slug table MUST be complete, unique, and lowercase kebab.

No em-dashes or en-dashes in output.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ingest.historical import philo
from pipeline4.historical_schema import ANCHOR_PATTERNS, HistoricalChunk

FIXTURES = Path(__file__).parent / "fixtures"

# (fixture filename, book number, expected treatise slug, expected work title)
_FIXTURE_BOOKS = (
    ("yonge_book01.html", 1, "de-opificio", "On the Creation"),
    ("yonge_book25.html", 25, "de-vita-mosis-ii", "On the Life of Moses, II"),
    (
        "yonge_book40.html",
        40,
        "legatio-ad-gaium",
        "On the Embassy to Gaius: The First Part of the Treatise on Virtues",
    ),
)

_PHILO_ANCHOR_RE = ANCHOR_PATTERNS["philo"]
_DASH_CHARS = ("—", "–")  # em-dash, en-dash


def _parse_fixtures() -> list[HistoricalChunk]:
    chunks: list[HistoricalChunk] = []
    for fname, book, _slug, _title in _FIXTURE_BOOKS:
        path = FIXTURES / fname
        assert path.is_file(), f"missing fixture {path}"
        chunks.extend(philo.parse_book(path.read_bytes(), book))
    return chunks


@pytest.fixture(scope="module")
def chunks() -> list[HistoricalChunk]:
    return _parse_fixtures()


@pytest.fixture(scope="module")
def by_book(chunks: list[HistoricalChunk]) -> dict[str, list[HistoricalChunk]]:
    grouped: dict[str, list[HistoricalChunk]] = {}
    for c in chunks:
        slug = c.source.anchor_id.rsplit(".", 1)[0]  # philo.<slug>
        grouped.setdefault(slug, []).append(c)
    return grouped


# ---------------------------------------------------------------------------
# Contract: adapter shape
# ---------------------------------------------------------------------------


def test_source_slugs_declared() -> None:
    assert philo.SOURCE_SLUGS == ("philo",)


def test_parse_is_callable() -> None:
    assert callable(philo.parse)
    assert callable(philo.parse_book)


# ---------------------------------------------------------------------------
# The 45-row treatise-slug table is the load-bearing required artifact
# ---------------------------------------------------------------------------


def test_treatise_table_complete() -> None:
    assert set(philo.BOOK_TO_TREATISE) == set(range(1, 46))
    assert len(philo.BOOK_TO_TREATISE) == 45


def test_treatise_slugs_unique_and_kebab() -> None:
    slugs = [s for s, _ in philo.BOOK_TO_TREATISE.values()]
    assert len(slugs) == len(set(slugs)), "duplicate treatise slug"
    kebab = re.compile(r"^[a-z0-9-]+$")
    for s in slugs:
        assert kebab.match(s), f"slug {s!r} is not lowercase kebab"


def test_collision_slugs_carry_explicit_ordinal() -> None:
    # The recon flags I/II/III collisions; the slug must disambiguate them.
    table = philo.BOOK_TO_TREATISE
    assert table[2][0] == "legum-allegoriae-i"
    assert table[3][0] == "legum-allegoriae-ii"
    assert table[4][0] == "legum-allegoriae-iii"
    assert table[24][0] == "de-vita-mosis-i"
    assert table[25][0] == "de-vita-mosis-ii"
    assert table[27][0] == "de-specialibus-legibus-i"
    assert table[30][0] == "de-specialibus-legibus-iv"
    assert table[41][0] == "qg-i"
    assert table[43][0] == "qg-iii"


def test_fixture_book_slug_mapping() -> None:
    for _fname, book, slug, title in _FIXTURE_BOOKS:
        assert philo.BOOK_TO_TREATISE[book][0] == slug
        assert philo.BOOK_TO_TREATISE[book][1] == title


# ---------------------------------------------------------------------------
# Every parsed record validates and every anchor matches the pattern
# ---------------------------------------------------------------------------


def test_all_records_validate(chunks: list[HistoricalChunk]) -> None:
    assert chunks, "fixtures produced zero chunks"
    for c in chunks:
        # Round-trip through the model to prove every emitted record is clean.
        HistoricalChunk.model_validate(c.model_dump(mode="json"))


def test_all_anchors_match_pattern(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        assert c.chunk_id == c.source.anchor_id
        assert _PHILO_ANCHOR_RE.match(c.source.anchor_id), c.source.anchor_id


def test_fixed_metadata(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        assert c.source_type == "jewish-philosopher"
        assert c.source.source_slug == "philo"
        assert c.source.author == "Philo of Alexandria"
        assert c.source.language == "en"
        assert c.source.translator == "C. D. Yonge (1854)"
        assert c.source.edition == "earlychristianwritings.com Yonge"
        assert c.source.work_id == c.source.anchor_id.rsplit(".", 1)[0]
        assert c.license == "PD"
        assert c.redistribute is True
        assert c.provenance.original_language == "el"


def test_fixture_books_are_greek_chain_complete(chunks: list[HistoricalChunk]) -> None:
    # The three fixture treatises are all Greek-preserved (not Armenian-via-Latin).
    for c in chunks:
        assert c.provenance.witness_chain == [
            "greek-original",
            "english-yonge-1854",
        ]
        assert c.provenance.loss_status == "complete"
        # Non-contested, embedding surface equals citation surface.
        assert c.contested_interpolation.type == "none"
        assert c.contested_interpolation.note is None
        assert c.text == c.text_to_embed


# ---------------------------------------------------------------------------
# Anchor structure per fixture treatise: gap-free 1..N
# ---------------------------------------------------------------------------


def test_anchor_sequence_gap_free(
    by_book: dict[str, list[HistoricalChunk]],
) -> None:
    for _fname, _book, slug, _title in _FIXTURE_BOOKS:
        group = by_book[f"philo.{slug}"]
        paras = sorted(int(c.source.anchor_id.rsplit(".", 1)[1]) for c in group)
        assert paras[0] == 1, f"{slug} does not start at paragraph 1"
        assert paras == list(range(1, len(paras) + 1)), f"{slug} has gaps: {paras}"


def test_embassy_typo_marker_recovered(
    by_book: dict[str, list[HistoricalChunk]],
) -> None:
    # Book 40 contains the "( 292)" internal-space typo; paragraph 292 must be
    # present and the treatise must reach its true length (373 paragraphs).
    group = by_book["philo.legatio-ad-gaium"]
    paras = {int(c.source.anchor_id.rsplit(".", 1)[1]) for c in group}
    assert 292 in paras, "the '( 292)' typo paragraph was dropped"
    assert max(paras) == 373, f"Embassy truncated at {max(paras)}"


def test_opificio_first_paragraph_text(
    by_book: dict[str, list[HistoricalChunk]],
) -> None:
    first = by_book["philo.de-opificio"][0]
    assert first.source.anchor_id == "philo.de-opificio.1"
    # Yonge's opening sentence of On the Creation.
    assert first.text.startswith("Of other lawgivers")
    # The title footnote markers must not survive into the prose.
    assert "{" not in first.text and "}" not in first.text


# ---------------------------------------------------------------------------
# Editorial apparatus is stripped; no banned dashes
# ---------------------------------------------------------------------------


def test_no_editorial_apparatus_leaks(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        assert "{" not in c.text and "}" not in c.text, c.source.anchor_id
        assert "(#" not in c.text, c.source.anchor_id
        # The chrome breadcrumb must never appear.
        assert "The Works of Philo" not in c.text


def test_no_em_or_en_dashes(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        for dash in _DASH_CHARS:
            assert dash not in c.text, f"dash in {c.source.anchor_id}"
            assert dash not in c.text_to_embed


# ---------------------------------------------------------------------------
# Count plausibility and determinism
# ---------------------------------------------------------------------------


def test_count_plausible(chunks: list[HistoricalChunk]) -> None:
    # De Opificio (172) + De Vita Mosis II (292) + Legatio ad Gaium (373).
    assert len(chunks) == 172 + 292 + 373


def test_deterministic_order() -> None:
    first = [c.chunk_id for c in _parse_fixtures()]
    second = [c.chunk_id for c in _parse_fixtures()]
    assert first == second
    assert len(first) == len(set(first)), "duplicate anchor in fixture parse"


def test_each_fixture_produces_its_slug(
    by_book: dict[str, list[HistoricalChunk]],
) -> None:
    for _fname, _book, slug, _title in _FIXTURE_BOOKS:
        assert f"philo.{slug}" in by_book
        assert by_book[f"philo.{slug}"], f"no chunks for {slug}"
