"""Tests for the Sefaria Mishnah adapter (ingest/historical/sefaria_mishnah.py).

These tests run fully offline against cached upstream fixtures under
tests/historical/fixtures/mishnah/ (three representative tractates):

  - sanhedrin/hebrew_merged.json    Mishnah Sanhedrin (11 Sefaria chapters)
  - berakhot/hebrew_merged.json     Mishnah Berakhot (Seder Zeraim sample)
  - pirkei-avot/hebrew_merged.json  Pirkei Avot (slug-normalization edge case)

They exist to BREAK the adapter, not rubber-stamp it:
  - every parsed record MUST validate as a HistoricalChunk;
  - every anchor MUST match the mishnah pattern in the schema;
  - Mishnah Sanhedrin 10.1 (the "Helek" mishnah, rabbinic anchor for resurrection
    of the dead) MUST be an atomic chunk with chunk_id == anchor_id;
  - inline HTML (<i>, <br>, Vilna-page overlay spans) MUST be stripped from text
    and text_to_embed;
  - the Hebrew original-language discipline holds: text_to_embed == text, license
    is PD, translator and author are None;
  - parsing MUST be deterministic with no duplicate anchors;
  - the live parse MUST land inside the catalog live_corpus_bound [4000, 4400].

No em-dashes or en-dashes anywhere in output.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

from ingest.historical import sefaria_mishnah as adapter
from pipeline4.historical_schema import ANCHOR_PATTERNS, HistoricalChunk

FIXTURES = Path(__file__).parent / "fixtures" / "mishnah"

_DASHES = (chr(0x2014), chr(0x2013))  # em-dash, en-dash (built so this file stays dash-clean)
_HTML_TAG = re.compile(r"<[^>]+>")

# (slug, work_title) for each staged fixture tractate.
_FIXTURE_TRACTATES = (
    ("sanhedrin", "Mishnah Sanhedrin"),
    ("berakhot", "Mishnah Berakhot"),
    ("pirkei-avot", "Pirkei Avot"),
)


def _parse_fixture(slug: str, work_title: str) -> list[HistoricalChunk]:
    path = FIXTURES / slug / "hebrew_merged.json"
    return list(adapter._parse_tractate(path, slug, work_title))


@pytest.fixture(scope="module")
def sanhedrin() -> list[HistoricalChunk]:
    return _parse_fixture("sanhedrin", "Mishnah Sanhedrin")


@pytest.fixture(scope="module")
def berakhot() -> list[HistoricalChunk]:
    return _parse_fixture("berakhot", "Mishnah Berakhot")


@pytest.fixture(scope="module")
def pirkei_avot() -> list[HistoricalChunk]:
    return _parse_fixture("pirkei-avot", "Pirkei Avot")


@pytest.fixture(scope="module")
def all_chunks(
    sanhedrin: list[HistoricalChunk],
    berakhot: list[HistoricalChunk],
    pirkei_avot: list[HistoricalChunk],
) -> list[HistoricalChunk]:
    return [*sanhedrin, *berakhot, *pirkei_avot]


# ---------------------------------------------------------------------------
# Contract: adapter shape
# ---------------------------------------------------------------------------


def test_source_slugs_declared() -> None:
    assert adapter.SOURCE_SLUGS == ("mishnah",)


def test_parse_is_callable() -> None:
    assert callable(adapter.parse)


def test_tractate_table_is_complete() -> None:
    # Sixty-three tractates, all slugs unique, all kebab-case.
    slugs = [s for s, _ in adapter._TRACTATES]
    assert len(slugs) == 63
    assert len(set(slugs)) == 63
    for s in slugs:
        assert re.fullmatch(r"[a-z0-9-]+", s), s


# ---------------------------------------------------------------------------
# Each fixture tractate yields chunks
# ---------------------------------------------------------------------------


def test_sanhedrin_yields_chunks(sanhedrin: list[HistoricalChunk]) -> None:
    assert sanhedrin, "Sanhedrin fixture produced zero chunks"


def test_berakhot_yields_chunks(berakhot: list[HistoricalChunk]) -> None:
    assert berakhot, "Berakhot fixture produced zero chunks"


def test_pirkei_avot_yields_chunks(pirkei_avot: list[HistoricalChunk]) -> None:
    assert pirkei_avot, "Pirkei Avot fixture produced zero chunks"


# ---------------------------------------------------------------------------
# All parsed records validate as HistoricalChunk
# ---------------------------------------------------------------------------


def test_all_records_validate(all_chunks: list[HistoricalChunk]) -> None:
    assert all_chunks
    for c in all_chunks:
        HistoricalChunk.model_validate(c.model_dump(mode="json"))


def test_all_records_fixed_metadata(all_chunks: list[HistoricalChunk]) -> None:
    for c in all_chunks:
        assert c.source_type == "jewish-rabbinic"
        assert c.source.source_slug == "mishnah"
        assert c.source.author is None
        assert c.source.translator is None
        assert c.source.language == "he"
        assert c.source.date_written_range == "c. 200 CE"
        assert c.license == "PD"
        assert c.redistribute is True
        assert c.chunk_id == c.source.anchor_id
        # Original-language discipline: embedding surface equals the text.
        assert c.text == c.text_to_embed
        # Provenance carries the pinned Hebrew witness chain.
        assert c.provenance.original_language == "he"
        assert c.provenance.loss_status == "complete"
        assert c.provenance.witness_chain == ["hebrew-torat-emet-357"]
        # Uncontested rabbinic text.
        assert c.contested_interpolation.type == "none"
        assert c.contested_interpolation.note is None
        assert c.contested_interpolation.redact_for_embedding is False


def test_all_anchors_match_pattern(all_chunks: list[HistoricalChunk]) -> None:
    pat = ANCHOR_PATTERNS["mishnah"]
    for c in all_chunks:
        assert pat.match(c.source.anchor_id), c.source.anchor_id


def test_work_id_and_title(
    sanhedrin: list[HistoricalChunk], pirkei_avot: list[HistoricalChunk]
) -> None:
    for c in sanhedrin:
        assert c.source.work_id == "mishnah.sanhedrin"
        assert c.source.work_title == "Mishnah Sanhedrin"
    # Pirkei Avot proves the "Mishnah " prefix is not required for the title and
    # the slug is the kebab of the Sefaria English name.
    for c in pirkei_avot:
        assert c.source.work_id == "mishnah.pirkei-avot"
        assert c.source.work_title == "Pirkei Avot"
        assert c.source.anchor_id.startswith("mishnah.pirkei-avot.")


# ---------------------------------------------------------------------------
# Sanhedrin 10.1 (the Helek mishnah): atomic chunk, present, non-empty
# ---------------------------------------------------------------------------


def test_sanhedrin_ten_one_present(sanhedrin: list[HistoricalChunk]) -> None:
    by_anchor = {c.chunk_id: c for c in sanhedrin}
    helek = by_anchor.get("mishnah.sanhedrin.10.1")
    assert helek is not None, "mishnah.sanhedrin.10.1 (the Helek mishnah) was not emitted"
    assert helek.chunk_id == helek.source.anchor_id
    # The opening clause "All Israel has a share in the World-to-Come". Match on
    # consonantal stems (nikkud-insensitive) so the assertion does not depend on
    # the exact combining-mark sequence of any Hebrew literal in this file.
    consonants = "".join(ch for ch in helek.text if "א" <= ch <= "ת")
    assert consonants.startswith("כלישראל")  # kol yisrael
    assert "חלק" in consonants  # chelek = "share"
    assert "לעולםהבא" in consonants  # la-olam ha-ba
    assert len(helek.text) > 50


# ---------------------------------------------------------------------------
# REQUIRED FLAG: inline HTML stripped from both surfaces
# ---------------------------------------------------------------------------


def test_no_residual_html(all_chunks: list[HistoricalChunk]) -> None:
    for c in all_chunks:
        assert not _HTML_TAG.search(c.text), f"residual HTML in {c.chunk_id} text"
        assert not _HTML_TAG.search(c.text_to_embed), f"residual HTML in {c.chunk_id} embed"


def test_text_is_nfc_and_nonempty(all_chunks: list[HistoricalChunk]) -> None:
    for c in all_chunks:
        assert c.text.strip(), c.chunk_id
        assert c.text == unicodedata.normalize("NFC", c.text)
        # No stray newlines or tab runs survived the whitespace collapse.
        assert "\n" not in c.text
        assert "  " not in c.text


def test_no_em_en_dashes_in_text(all_chunks: list[HistoricalChunk]) -> None:
    for c in all_chunks:
        for dash in _DASHES:
            assert dash not in c.text, f"dash in {c.chunk_id} text"
            assert dash not in c.text_to_embed, f"dash in {c.chunk_id} embed"


# ---------------------------------------------------------------------------
# Determinism and uniqueness
# ---------------------------------------------------------------------------


def test_deterministic_order() -> None:
    def run() -> list[str]:
        out: list[str] = []
        for slug, title in _FIXTURE_TRACTATES:
            out.extend(c.chunk_id for c in _parse_fixture(slug, title))
        return out

    first = run()
    second = run()
    assert first == second
    assert len(first) == len(set(first)), "duplicate anchors in fixture parse"


def test_missing_tractate_dir_is_skipped(tmp_path: Path) -> None:
    # A tractate without a staged hebrew_merged.json yields nothing, no error.
    missing = tmp_path / "ghost" / "hebrew_merged.json"
    assert list(adapter._parse_tractate(missing, "ghost", "Mishnah Ghost")) == []


# ---------------------------------------------------------------------------
# Live corpus: full parse lands inside the catalog live_corpus_bound
# ---------------------------------------------------------------------------


def test_live_parse_within_bound() -> None:
    # Requires the procured data/private/historical/mishnah/ tree. Skip cleanly
    # if procurement has not run in this environment.
    root = adapter.HISTORICAL_DATA_ROOT / "mishnah"
    if not root.is_dir():
        pytest.skip("data/private/historical/mishnah not staged")
    chunks = list(adapter.parse())
    if not chunks:
        pytest.skip("mishnah tree present but empty")
    count = len(chunks)
    assert 4000 <= count <= 4400, f"chunk count {count} outside live_corpus_bound"
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), "duplicate chunk_id in live parse"
    # The Helek mishnah survives the full deterministic walk.
    assert "mishnah.sanhedrin.10.1" in set(ids)
