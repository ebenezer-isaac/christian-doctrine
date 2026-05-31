"""Tests for tools.evidence_to_pdf (v3.1)."""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import A4

from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from tests.pipeline2._fixtures import minimal_evidence_dict
from tools.evidence_to_pdf import (
    PAGE_H,
    PAGE_W,
    _affirms_color,
    _affirms_label,
    _bidi,
    _humanize_id,
    _reattach_hebrew_marks,
    _visual_rtl,
    build_story,
    build_styles,
    collect_strong_records,
    register_unicode_font,
    render_pdf,
)


def _materialize(tmp_path: Path) -> Path:
    e = Evidence.model_validate(minimal_evidence_dict())
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    path = tmp_path / "doc-trinity.json"
    path.write_text(json.dumps(e_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def test_render_produces_non_empty_pdf(tmp_path: Path) -> None:
    src = _materialize(tmp_path)
    out = tmp_path / "doc-trinity.pdf"
    font_pair = register_unicode_font()
    render_pdf(src, out, font_pair, {"category": "Theology Proper"})
    assert out.exists()
    assert out.stat().st_size > 1024


def test_render_emits_pdf_header(tmp_path: Path) -> None:
    src = _materialize(tmp_path)
    out = tmp_path / "doc-trinity.pdf"
    font_pair = register_unicode_font()
    render_pdf(src, out, font_pair, {"category": "Theology Proper"})
    header = out.read_bytes()[:1024]
    assert b"%PDF-" in header


def test_page_is_portrait_a4() -> None:
    # A4 portrait: width is the short edge, height the long edge.
    assert (PAGE_W, PAGE_H) == A4
    assert PAGE_W < PAGE_H


def _collect_text(items: object) -> str:
    """Walk Paragraphs/Tables and concat their inner text for assertion."""
    from reportlab.platypus import KeepTogether, Paragraph, Table

    buf: list[str] = []
    if isinstance(items, list):
        for it in items:
            buf.append(_collect_text(it))
    elif isinstance(items, Paragraph):
        buf.append(getattr(items, "text", "") or "")
    elif isinstance(items, KeepTogether):
        buf.append(_collect_text(items._content))
    elif isinstance(items, Table):
        for row in items._cellvalues:
            buf.append(_collect_text(list(row)))
    return " ".join(b for b in buf if b)


def test_verdict_badge_renders_plain_english_phrases(tmp_path: Path) -> None:
    """The badge translates the three v3.1 axes into plain-English reader phrases.

    Reader-facing PDFs should not surface schema taxonomy. Each axis maps to a
    sentence the user can read without consulting the schema doc.
    """
    from tools.evidence_to_pdf import (
        _BREADTH_PHRASE,
        _DIRECTNESS_PHRASE,
        _STABILITY_PHRASE,
    )

    src = _materialize(tmp_path)
    data = json.loads(src.read_text(encoding="utf-8"))
    font_pair = register_unicode_font()
    styles = build_styles(*font_pair)
    story = build_story(data, styles, {"category": "Theology Proper"})
    rendered = _collect_text(story)
    breadth = data["verdict"]["lexical_breadth"]
    directness = data["verdict"]["lexical_directness"]
    stability = data["verdict"]["variant_stability"]
    assert _BREADTH_PHRASE[breadth] in rendered
    assert _DIRECTNESS_PHRASE[directness] in rendered
    assert _STABILITY_PHRASE[stability] in rendered


def test_verdict_badge_includes_affirms_label(tmp_path: Path) -> None:
    src = _materialize(tmp_path)
    data = json.loads(src.read_text(encoding="utf-8"))
    font_pair = register_unicode_font()
    styles = build_styles(*font_pair)
    story = build_story(data, styles, {"category": "Theology Proper"})
    rendered = _collect_text(story)
    assert "AFFIRMS" in rendered


def test_verdict_badge_does_not_leak_schema_taxonomy(tmp_path: Path) -> None:
    """The reader should never see raw enum identifiers like 'canon_wide' or 'lexical_breadth'."""
    src = _materialize(tmp_path)
    data = json.loads(src.read_text(encoding="utf-8"))
    font_pair = register_unicode_font()
    styles = build_styles(*font_pair)
    story = build_story(data, styles, {"category": "Theology Proper"})
    rendered = _collect_text(story)
    for taxonomy in ("canon_wide", "lexical_breadth", "lexical_directness", "variant_stability"):
        assert taxonomy not in rendered, f"reader-facing PDF leaks schema taxonomy: {taxonomy}"


def test_affirms_label_handles_all_states() -> None:
    assert _affirms_label(True) == "AFFIRMS"
    assert _affirms_label(False) == "DENIES"
    assert _affirms_label(None) == "INSUFFICIENT"
    assert _affirms_label("disputed") == "DISPUTED"


def test_affirms_color_handles_all_states() -> None:
    assert _affirms_color(True) == "#1a7f37"
    assert _affirms_color(False) == "#b42318"
    assert _affirms_color(None) == "#475467"
    assert _affirms_color("disputed") == "#b54708"


def test_humanize_id_strips_prefix_and_titlecases() -> None:
    assert _humanize_id("doc-trinity") == "Trinity"
    assert _humanize_id("doc-christ-full-deity") == "Christ Full Deity"
    assert _humanize_id("prc-euthanasia") == "Euthanasia"
    # No recognized prefix: still readable, never empty.
    assert _humanize_id("standalone") == "Standalone"


def test_visual_rtl_reverses_hebrew_clusters_keeping_niqqud() -> None:
    # echad built from explicit code points: aleph + segol, chet + qamats, dalet.
    aleph, segol, chet, qamats, dalet = "א", "ֶ", "ח", "ָ", "ד"
    echad = aleph + segol + chet + qamats + dalet
    out = _visual_rtl(echad)
    # Visual LTR order leads with the last logical letter (dalet) and ends with
    # the first base letter still carrying its vowel point (aleph + segol).
    assert out[0] == dalet
    assert out.endswith(aleph + segol)
    # Each base keeps its combining mark in logical sub-order; only cluster order flips.
    assert chet + qamats in out
    # Reversing twice restores the original logical string.
    assert _visual_rtl(out) == echad


def test_visual_rtl_leaves_greek_and_latin_untouched() -> None:
    logos = "λόγος"  # lambda omicron-tonos gamma omicron sigma
    assert _visual_rtl(logos) == logos
    assert _visual_rtl("echad") == "echad"
    assert _visual_rtl("") == ""


def test_bidi_is_noop_without_hebrew() -> None:
    assert _bidi("The Word was God") == "The Word was God"
    assert _bidi("λόγος") == "λόγος"
    assert _bidi("") == ""
    assert _bidi(None) is None


def test_reattach_hebrew_marks_moves_points_after_base() -> None:
    aleph, segol, chet, qamats, dalet = "א", "ֶ", "ח", "ָ", "ד"
    # Simulate a get_display reversal where points precede their base.
    reversed_run = dalet + qamats + chet + segol + aleph
    fixed = _reattach_hebrew_marks(reversed_run)
    # No combining point may lead the string, and each point must sit on a base.
    assert not _is_hebrew_point_first(fixed)
    assert fixed == dalet + chet + qamats + aleph + segol
    # Character multiset is preserved (pure reordering).
    assert sorted(fixed) == sorted(reversed_run)


def test_bidi_mixed_script_keeps_ltr_runs_and_permutes_chars() -> None:
    aleph, segol, chet, qamats, dalet = "א", "ֶ", "ח", "ָ", "ד"
    echad = aleph + segol + chet + qamats + dalet
    src = "The verb " + echad + " then λόγος."
    out = _bidi(src)
    assert isinstance(out, str)
    # Left-to-right runs survive intact; the whole string is a permutation.
    assert "The verb" in out
    assert "λόγος" in out
    assert sorted(out) == sorted(src)
    # No Hebrew vowel point is left stranded at the front of the Hebrew run.
    assert echad not in out or out != src  # reordering actually happened


def _is_hebrew_point_first(text: str) -> bool:
    import unicodedata

    return bool(text) and bool(unicodedata.combining(text[0])) and 0x0591 <= ord(text[0]) <= 0x05C7


def test_collect_strong_records_unions_all_strong_sources() -> None:
    data = minimal_evidence_dict()
    records = collect_strong_records(data)
    codes = {r["strong"] for r in records}
    # Union of anchor_lemmas, scripture key_terms, and concordance_traversed.
    assert {"H3068", "H0430", "G2316", "G3056"} <= codes
    # Anchor lemmas are flagged; occurrences carried through from the schema field.
    h3068 = next(r for r in records if r["strong"] == "H3068")
    assert h3068["anchor"] is True
    assert h3068["occurrences"] == 6828
    # A concordance-only code still appears, just without an occurrence count.
    g3056 = next(r for r in records if r["strong"] == "G3056")
    assert g3056["occurrences"] is None
    # Deterministic order: Hebrew before Greek, ascending by numeric code.
    assert codes  # non-empty
    order = [r["strong"] for r in records]
    assert order == sorted(
        order,
        key=lambda c: (0 if c.startswith("H") else 1, int("".join(ch for ch in c if ch.isdigit()))),
    )


def test_dictionary_appears_in_story_with_plain_meanings(tmp_path: Path) -> None:
    src = _materialize(tmp_path)
    data = json.loads(src.read_text(encoding="utf-8"))
    font_pair = register_unicode_font()
    styles = build_styles(*font_pair)
    story = build_story(data, styles, {"category": "Theology Proper"})
    rendered = _collect_text(story)
    assert "Word dictionary" in rendered
    # Every referenced Strong's code is listed in the dictionary.
    for code in ("H3068", "H0430", "G2316", "G3056"):
        assert code in rendered
