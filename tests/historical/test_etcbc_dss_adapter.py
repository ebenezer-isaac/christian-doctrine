"""Tests for the ETCBC/dss Text-Fabric adapter (ingest/historical/etcbc_dss.py).

These tests run fully offline against a self-contained, trimmed Text-Fabric
fixture under tests/historical/fixtures/dss_tf/2.0/. The fixture is real ETCBC
data (CC-BY-NC-4.0) renumbered to a handful of nodes covering:

  - 1QS column 4 (columnar sectarian, Hebrew, the Two Spirits passage),
  - 11Q19 column 2 (the Temple Scroll: columnar sectarian, two-leading-digit
    cave siglum, now EMITTED because QUMRAN_SLUG_RE/DSS_ANCHOR_RE accept caves
    1 through 11),
  - 4Q521 fragment 2ii+4 (fragmentary sectarian, exercises the '+' separator),
  - 1QIsaa column 1 (columnar biblical),
  - CD column 1 (expected SKIPPED: 'cd' cannot form a DSS_ANCHOR_RE anchor,
    the regex needs a 'q').

The tests exist to BREAK the adapter, not rubber-stamp it. They assert the
Option A discipline (text == text_to_embed verbatim), the non-redistributable
CC-BY-NC license posture, anchor regex conformance, source_type assignment from
the biblical flag, deterministic byte-identical re-parse, the honest skipping of
schema-unrepresentable sigla, and the fragment-label collision guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.historical import etcbc_dss
from pipeline4.historical_schema import (
    DSS_ANCHOR_RE,
    NAMED_SOURCE_SLUGS,
    QUMRAN_SLUG_RE,
    HistoricalChunk,
)

FIXTURE_TF = Path(__file__).parent / "fixtures" / "dss_tf" / "2.0"


@pytest.fixture(scope="module")
def chunks() -> list[HistoricalChunk]:
    assert FIXTURE_TF.is_dir(), f"missing fixture TF dir {FIXTURE_TF}"
    return list(etcbc_dss._parse_tf_dir(FIXTURE_TF))


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


def test_fixture_yields_chunks(chunks: list[HistoricalChunk]) -> None:
    assert chunks, "adapter produced no chunks from the fixture"
    # Every record validates as a HistoricalChunk (parse() constructs them, so a
    # schema failure would already have raised; re-validate defensively).
    for c in chunks:
        HistoricalChunk.model_validate(c.model_dump())


def test_known_marquee_scroll_yields_chunks(
    chunks: list[HistoricalChunk],
) -> None:
    # 1QS (Community Rule) is a marquee scroll and MUST be present.
    one_qs = [c for c in chunks if c.source.source_slug == "1qs"]
    assert one_qs, "no 1QS chunks parsed from the fixture"
    # Anchors are columnar: 1qs.col04.lineNN.
    assert all(c.source.anchor_id.startswith("1qs.col04.line") for c in one_qs)


# ---------------------------------------------------------------------------
# Anchor conformance (DSS_ANCHOR_RE)
# ---------------------------------------------------------------------------


def test_all_anchors_match_dss_regex(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        assert DSS_ANCHOR_RE.match(c.source.anchor_id), (
            f"anchor {c.source.anchor_id!r} does not match DSS_ANCHOR_RE"
        )
        # chunk_id convention: equal to anchor_id.
        assert c.chunk_id == c.source.anchor_id


def test_all_slugs_validate(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        slug = c.source.source_slug
        assert slug in NAMED_SOURCE_SLUGS or QUMRAN_SLUG_RE.match(slug), (
            f"slug {slug!r} is not a registered DSS source_slug"
        )
        assert slug == slug.lower(), "scroll slug must be lowercase"


def test_columnar_and_fragmentary_anchor_forms(
    chunks: list[HistoricalChunk],
) -> None:
    by_id = {c.chunk_id: c for c in chunks}
    # Columnar form.
    assert "1qs.col04.line01" in by_id
    # Fragmentary form with the '+' separator mapped to a letter ('p').
    frag = next(
        (c for c in chunks if c.source.source_slug == "4q521"), None
    )
    assert frag is not None, "4Q521 fragmentary scroll missing from fixture"
    assert ".f" in frag.chunk_id and "col" not in frag.chunk_id.split(".")[1]
    # The original siglum is preserved in anchor_alt_citation for fragmentary
    # scrolls so the lossy sanitization stays auditable.
    assert frag.source.anchor_alt_citation is not None
    assert "2ii+4" in frag.source.anchor_alt_citation


# ---------------------------------------------------------------------------
# Honest skipping of schema-unrepresentable sigla
# ---------------------------------------------------------------------------


def test_unrepresentable_sigla_are_skipped(
    chunks: list[HistoricalChunk],
) -> None:
    slugs = {c.source.source_slug for c in chunks}
    # CD is an allowed source_slug but cd.colNN.lineNN cannot match DSS_ANCHOR_RE
    # (the regex needs a 'q'); the adapter skips it rather than fudging. Genuinely
    # non-cave-Q sigla (CD, Mas*, Mur*, PAM*, 5/6Hev*) stay unrepresentable.
    assert "cd" not in slugs


def test_two_digit_cave_scroll_is_emitted(
    chunks: list[HistoricalChunk],
) -> None:
    # 11Q19 (the Temple Scroll) has a two-leading-digit cave siglum. The relaxed
    # QUMRAN_SLUG_RE / DSS_ANCHOR_RE (caves 1 through 11) now admit it, so it MUST
    # be present and validate; the corpus is kept in full, not trimmed.
    temple = [c for c in chunks if c.source.source_slug == "11q19"]
    assert temple, "11Q19 (Temple Scroll) missing: two-digit-cave scroll was dropped"
    for c in temple:
        assert c.source.anchor_id.startswith("11q19.col"), (
            f"unexpected 11Q19 anchor {c.source.anchor_id!r}"
        )
        assert DSS_ANCHOR_RE.match(c.source.anchor_id)
        assert c.source.work_title == "Temple Scroll"
        assert c.source_type == "qumran-sectarian"
        # Cave label in the witness chain reflects the two-digit cave number.
        assert "qumran-cave-11" in c.provenance.witness_chain
        HistoricalChunk.model_validate(c.model_dump())


# ---------------------------------------------------------------------------
# Option A discipline + license posture
# ---------------------------------------------------------------------------


def test_option_a_text_equals_text_to_embed(
    chunks: list[HistoricalChunk],
) -> None:
    for c in chunks:
        assert c.text == c.text_to_embed, (
            "Option A discipline violated: text_to_embed must equal text "
            f"(no engine gloss) for {c.chunk_id}"
        )
        assert c.contested_interpolation.type == "none"
        assert c.contested_interpolation.redact_for_embedding is False


def test_text_preserves_transliteration_flags(
    chunks: list[HistoricalChunk],
) -> None:
    # The verbatim ETCBC transliteration carries bracket/flag glyphs; at least
    # one fixture chunk must retain a reconstruction bracket or uncertainty flag,
    # proving the adapter does not strip them.
    flag_chars = set("[]()#?")
    assert any(any(ch in flag_chars for ch in c.text) for c in chunks), (
        "no transliteration flags survived; the adapter is stripping brackets"
    )


def test_license_is_cc_by_nc_non_redistributable(
    chunks: list[HistoricalChunk],
) -> None:
    for c in chunks:
        assert c.license == "CC-BY-NC-4.0"
        assert c.redistribute is False
        assert c.license_note and "CC-BY-NC-4.0" in c.license_note


# ---------------------------------------------------------------------------
# source_type from the biblical flag
# ---------------------------------------------------------------------------


def test_source_type_tracks_biblical_flag(
    chunks: list[HistoricalChunk],
) -> None:
    by_slug = {}
    for c in chunks:
        by_slug.setdefault(c.source.source_slug, set()).add(c.source_type)
    # 1QIsaa is a biblical manuscript.
    assert by_slug.get("1qisaa") == {"qumran-biblical"}
    # 1QS is a sectarian rule text.
    assert by_slug.get("1qs") == {"qumran-sectarian"}


def test_language_codes(chunks: list[HistoricalChunk]) -> None:
    for c in chunks:
        assert c.source.language in {"hbo", "arc", "grc"}
        assert c.provenance.original_language == c.source.language


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_parse_is_deterministic() -> None:
    run1 = [c.model_dump(mode="json") for c in etcbc_dss._parse_tf_dir(FIXTURE_TF)]
    run2 = [c.model_dump(mode="json") for c in etcbc_dss._parse_tf_dir(FIXTURE_TF)]
    assert run1 == run2
    # Anchor order is stable and unique.
    ids = [r["chunk_id"] for r in run1]
    assert ids == sorted(set(ids), key=ids.index)
    assert len(ids) == len(set(ids)), "duplicate chunk_id in fixture output"


# ---------------------------------------------------------------------------
# Anchor builder unit tests (pure helper)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "fragment", "line", "expected"),
    [
        ("1qs", "4", "3", "1qs.col04.line03"),
        # Two-leading-digit cave now yields a valid anchor (regex is \\d{1,2}q...).
        ("11q19", "2", "1", "11q19.col02.line01"),
        ("11q5", "6", "12", "11q5.col06.line12"),  # 11QPsa, also two-digit cave
        ("cd", "1", "1", None),  # 'cd' cannot satisfy DSS_ANCHOR_RE (no 'q')
        ("4q427", "f7ii", "14", "4q427.f7ii.line14"),
        ("4q521", "f2ii+4", "1", "4q521.f2iip4.line01"),
        ("1q14", "f1_5", "1", "1q14.f1u5.line01"),
        ("4q394", "1", "5", "4q394.col01.line05"),
        ("1qs", "4", "x", None),  # non-numeric line label -> skip
    ],
)
def test_build_anchor(
    slug: str, fragment: str, line: str, expected: str | None
) -> None:
    assert etcbc_dss._build_anchor(slug, fragment, line) == expected


def test_build_anchor_separators_are_injective() -> None:
    # The classic collision: f1_5 (range) vs f15 (single fragment) MUST differ.
    a = etcbc_dss._build_anchor("4q176", "f4_5", "1")
    b = etcbc_dss._build_anchor("4q176", "f45", "1")
    assert a is not None and b is not None and a != b


def test_fragment_case_is_preserved() -> None:
    # The ETCBC dataset distinguishes fragment 'A' from fragment 'a'; the anchor
    # must not collapse them (4Q585 carries both).
    upper = etcbc_dss._build_anchor("4q585", "fA", "1")
    lower = etcbc_dss._build_anchor("4q585", "fa", "1")
    assert upper is not None and lower is not None and upper != lower


def test_line_language_majority_vote() -> None:
    assert etcbc_dss._line_language(["Hebrew", "Hebrew", "Aramaic"]) == "hbo"
    assert etcbc_dss._line_language(["Aramaic", "Aramaic"]) == "arc"
    assert etcbc_dss._line_language(["Greek"]) == "grc"
    assert etcbc_dss._line_language([]) == "hbo"
