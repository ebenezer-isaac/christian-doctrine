"""Render a v3.1 evidence/<id>.json file to a portrait A4 PDF.

Usage:
    python tools/evidence_to_pdf.py evidence/<id>.json
    python tools/evidence_to_pdf.py                           # every evidence/*.json
    python tools/evidence_to_pdf.py FILE --output-dir reports

Schema source of truth: docs/EVIDENCE_SCHEMA.md (v3.1). Every field read below is
a v3.1 field; the renderer never invents or writes schema fields. Sections, in
reading order: title (humanized id) -> breadcrumb -> verdict badge -> statement
under examination -> lay summary -> word dictionary (plain meanings for every
Strong's the file references) -> verdict rationale -> scripture -> cross
references -> complicating texts -> concordance traversed -> variants ->
hermeneutics -> stem audit -> citations -> license audit -> flags.

The word dictionary glosses come from the STEPBible brief lexicons (TBESH for
Hebrew, TBESG for Greek; CC-BY-4.0). They are read at render time from local
disk and never written back into the evidence JSON. If the lexicons are absent
the dictionary degrades to the lemma/transliteration the evidence file already
carries.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

try:  # Optional: correct bidi ordering for mixed Hebrew/Greek/English prose.
    from bidi import get_display as _get_display
except Exception:  # noqa: BLE001 - any import failure falls back gracefully.
    _get_display = None

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "evidence"
QUESTIONS_FILE = ROOT / "questions.json"
LEXICON_DIR = ROOT / "data" / "private" / "stepbible" / "Lexicons"

# Portrait A4 geometry. One content width drives every full-bleed element so
# nothing is hard-coded to a landscape page any more.
PAGE_W, PAGE_H = A4
MARGIN = 1.8 * cm
CONTENT_W = PAGE_W - 2 * MARGIN

# Palette.
INK = "#1f2a44"
SLATE = "#334155"
MUTED = "#64748b"
HAIRLINE = "#e2e8f0"
ZEBRA = "#f8fafc"
BAND = "#eef2f7"

AFFIRMS_COLOR = {
    True: "#1a7f37",
    False: "#b42318",
    None: "#475467",
    "disputed": "#b54708",
}

SUPPORTS_COLOR = {
    "for": "#1a7f37",
    "complicates": "#b54708",
    "neutral": "#475467",
}

_BASE_STRONG = re.compile(r"^([HG]\d+)")
_HEBREW = re.compile("[֐-׿יִ-ﭏ]")


def _visual_rtl(text: str) -> str:
    """Reorder a Hebrew string so it displays correctly in a left-to-right PDF.

    ReportLab does not implement the Unicode bidi algorithm, so right-to-left
    Hebrew is emitted in logical order and reads backwards. We reverse the order
    of grapheme clusters (each base letter plus its trailing combining marks,
    e.g. niqqud and dagesh) while keeping every cluster internally intact, which
    yields the correct visual order once the glyphs are laid out left to right.
    Strings with no Hebrew (Greek, Latin) are returned unchanged. Intended only
    for short pure-Hebrew lemma tokens, not mixed-script marked-up prose.
    """
    if not _HEBREW.search(text):
        return text
    clusters: list[str] = []
    for ch in text:
        if clusters and unicodedata.combining(ch):
            clusters[-1] += ch
        else:
            clusters.append(ch)
    return "".join(reversed(clusters))


def _is_hebrew_point(ch: str) -> bool:
    """Hebrew niqqud / cantillation marks (combining, U+0591..U+05C7)."""
    return bool(unicodedata.combining(ch)) and 0x0591 <= ord(ch) <= 0x05C7


def _reattach_hebrew_marks(text: str) -> str:
    """Move Hebrew points to follow their base letter after a bidi reversal.

    `get_display` reverses right-to-left runs but leaves combining Hebrew points
    *preceding* their base letter (Unicode rule L3 is left to the caller).
    ReportLab does no mark repositioning, so it would draw each vowel on the
    wrong consonant. We re-emit each buffered Hebrew point immediately after the
    next base character. Greek and Latin combining marks are out of range and
    pass through untouched in their already-correct left-to-right position.
    """
    out: list[str] = []
    pending: list[str] = []
    for ch in text:
        if _is_hebrew_point(ch):
            pending.append(ch)
        else:
            out.append(ch)
            out.extend(pending)
            pending = []
    out.extend(pending)
    return "".join(out)


def _bidi(value: object) -> object:
    """Reorder mixed-script text for correct display in a left-to-right PDF.

    Uses python-bidi (full Unicode bidi algorithm) for run ordering across
    interleaved Hebrew, Greek, English, and numbers, then repositions Hebrew
    points for ReportLab. Falls back to the dependency-free cluster reversal
    when python-bidi is unavailable, and is a no-op for text without Hebrew.
    """
    if not value:
        return value
    s = str(value)
    if not _HEBREW.search(s):
        return s
    if _get_display is None:
        return _visual_rtl(s)
    try:
        return _reattach_hebrew_marks(_get_display(s, base_dir="L"))
    except Exception:  # noqa: BLE001 - never let display reordering break a render.
        return _visual_rtl(s)


def register_unicode_font() -> tuple[str, str]:
    candidates = [
        (
            "Arial",
            "Arial-Bold",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ),
        (
            "DejaVuSans",
            "DejaVuSans-Bold",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    ]
    for reg, bold, reg_path, bold_path in candidates:
        if Path(reg_path).exists():
            pdfmetrics.registerFont(TTFont(reg, reg_path))
            if Path(bold_path).exists():
                pdfmetrics.registerFont(TTFont(bold, bold_path))
                return reg, bold
            return reg, reg
    return "Helvetica", "Helvetica-Bold"


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def _humanize_id(qid: str) -> str:
    """doc-christ-full-deity -> Christ Full Deity; prc-euthanasia -> Euthanasia."""
    body = re.sub(r"^(doc|prc|q)-", "", qid)
    words = [w for w in body.replace("_", "-").split("-") if w]
    return " ".join(w.capitalize() for w in words) or qid


def _affirms_label(value: object) -> str:
    if value is True:
        return "AFFIRMS"
    if value is False:
        return "DENIES"
    if value is None:
        return "INSUFFICIENT"
    return str(value).upper()


def _affirms_color(value: object) -> str:
    if value is True:
        return AFFIRMS_COLOR[True]
    if value is False:
        return AFFIRMS_COLOR[False]
    if value is None:
        return AFFIRMS_COLOR[None]
    return AFFIRMS_COLOR.get("disputed", "#475467")


def load_questions_index() -> dict[str, dict[str, Any]]:
    if not QUESTIONS_FILE.exists():
        return {}
    raw = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    items = raw.get("questions") if isinstance(raw, dict) else raw
    return {q["id"]: q for q in (items or []) if isinstance(q, dict) and "id" in q}


# ---------------------------------------------------------------------------
# Strong's lexicon glosses (STEPBible TBESH / TBESG, CC-BY-4.0).
# ---------------------------------------------------------------------------

_LEX_COL_STRONG = 0
_LEX_COL_SCRIPT = 3
_LEX_COL_TRANSLIT = 4
_LEX_COL_GLOSS = 6


def _base_strong(code: str) -> str:
    """H6213A / H6213a / H6213 -> H6213; tolerant of dStrong sense suffixes."""
    m = _BASE_STRONG.match(code.strip())
    return m.group(1) if m else code.strip()


def _lex_cell(parts: list[str], index: int) -> str:
    """Safely read a stripped tab-separated lexicon column."""
    return parts[index].strip() if index < len(parts) else ""


def _clean_gloss(gloss: str) -> str:
    """STEPBible glosses read 'general: specific'; keep the general lay sense."""
    head = gloss.split(":", 1)[0].strip()
    return head or gloss.strip()


def _lexicon_data_start(lines: list[str]) -> int:
    for idx, line in enumerate(lines):
        if line.startswith("eStrong") and "dStrong" in line:
            return idx + 1
    return 0


@lru_cache(maxsize=1)
def _full_gloss_map() -> dict[str, dict[str, str]]:
    """Parse both brief lexicons once into base_strong -> {gloss, script, translit}.

    Keeps the first (primary) sense per base code. Returns an empty map when the
    private lexicon files are not present on disk, so the renderer stays usable
    without them.
    """
    files = [
        LEXICON_DIR
        / "TBESH - Translators Brief lexicon of Extended Strongs for Hebrew - STEPBible.org CC BY.txt",
        LEXICON_DIR
        / "TBESG - Translators Brief lexicon of Extended Strongs for Greek - STEPBible.org CC BY.txt",
    ]
    out: dict[str, dict[str, str]] = {}
    for path in files:
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for raw in lines[_lexicon_data_start(lines):]:
            if "\t" not in raw:
                continue
            parts = raw.rstrip("\r").split("\t")
            code = parts[_LEX_COL_STRONG].strip() if parts else ""
            if not _BASE_STRONG.match(code):
                continue
            base = _base_strong(code)
            if base in out:
                continue
            out[base] = {
                "gloss": _clean_gloss(_lex_cell(parts, _LEX_COL_GLOSS)),
                "script": _lex_cell(parts, _LEX_COL_SCRIPT),
                "translit": _lex_cell(parts, _LEX_COL_TRANSLIT).replace(".", ""),
            }
    return out


def collect_strong_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Union every Strong's the evidence file references, with display fields.

    Reads only v3.1 fields: lexical_evidence.anchor_lemmas[],
    lexical_evidence.scripture[].key_terms[], lexical_evidence.concordance_traversed[].
    Original-script lemma and transliteration prefer the evidence file's own
    values; the plain meaning and any gap-filling come from the brief lexicons.
    """
    lex = data.get("lexical_evidence", {}) or {}
    glosses = _full_gloss_map()

    ev_lemma: dict[str, str] = {}
    ev_translit: dict[str, str] = {}
    occurrences: dict[str, int] = {}
    anchors: set[str] = set()
    codes: set[str] = set()

    for al in lex.get("anchor_lemmas") or []:
        code = _base_strong(str(al.get("strong", "")))
        if not code:
            continue
        codes.add(code)
        if al.get("lemma"):
            ev_lemma[code] = str(al["lemma"])
        if al.get("transliteration"):
            ev_translit[code] = str(al["transliteration"])
        if isinstance(al.get("occurrences_in_canon"), int):
            occurrences[code] = al["occurrences_in_canon"]
        if al.get("in_anchors"):
            anchors.add(code)

    for sc in lex.get("scripture") or []:
        for kt in sc.get("key_terms") or []:
            code = _base_strong(str(kt.get("strong", "")))
            if not code:
                continue
            codes.add(code)
            if kt.get("lemma") and code not in ev_lemma:
                ev_lemma[code] = str(kt["lemma"])

    for code in lex.get("concordance_traversed") or []:
        base = _base_strong(str(code))
        if base:
            codes.add(base)

    records: list[dict[str, Any]] = []
    for code in codes:
        gl = glosses.get(code, {})
        records.append(
            {
                "strong": code,
                "lemma": ev_lemma.get(code) or gl.get("script", ""),
                "translit": ev_translit.get(code) or gl.get("translit", ""),
                "meaning": gl.get("gloss", ""),
                "occurrences": occurrences.get(code),
                "anchor": code in anchors,
            }
        )

    def sort_key(r: dict[str, Any]) -> tuple[int, int]:
        code = r["strong"]
        lang = 0 if code.startswith("H") else 1
        digits = re.sub(r"\D", "", code) or "0"
        return (lang, int(digits))

    return sorted(records, key=sort_key)


# ---------------------------------------------------------------------------
# Styles and shared flowable builders.
# ---------------------------------------------------------------------------


def build_styles(regular: str, bold: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    body = ParagraphStyle(
        "Body", parent=base, fontName=regular, fontSize=9.5, leading=13.5, spaceAfter=6
    )
    return {
        "title": ParagraphStyle(
            "Title", parent=body, fontName=bold, fontSize=22, leading=25, spaceAfter=1,
            textColor=colors.HexColor(INK),
        ),
        "tag": ParagraphStyle(
            "Tag", parent=body, fontName=regular, fontSize=8.5, leading=11,
            textColor=colors.HexColor(MUTED), spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=body, fontName=regular, fontSize=9, leading=12,
            textColor=colors.HexColor(MUTED), spaceAfter=2,
        ),
        "verdict_big": ParagraphStyle(
            "VerdictBig", parent=body, fontName=bold, fontSize=21, leading=23,
        ),
        "verdict_meta": ParagraphStyle(
            "VerdictMeta", parent=body, fontName=regular, fontSize=10.5, leading=14,
            alignment=2, textColor=colors.HexColor(SLATE),
        ),
        "h2": ParagraphStyle(
            "H2", parent=body, fontName=bold, fontSize=12.5, leading=15,
            spaceBefore=4, spaceAfter=2, textColor=colors.HexColor(INK),
        ),
        "h3": ParagraphStyle(
            "H3", parent=body, fontName=bold, fontSize=10.5, leading=13.5,
            spaceBefore=4, spaceAfter=1, textColor=colors.HexColor(SLATE),
        ),
        "body": body,
        "small": ParagraphStyle(
            "Small", parent=body, fontName=regular, fontSize=8, leading=10.5,
            textColor=colors.HexColor(MUTED),
        ),
        "statement": ParagraphStyle(
            "Statement", parent=body, fontName=regular, fontSize=11, leading=15.5,
            textColor=colors.HexColor("#0f172a"), spaceAfter=0,
        ),
        "th": ParagraphStyle(
            "Th", parent=body, fontName=bold, fontSize=8.5, leading=11,
            textColor=colors.white, spaceAfter=0,
        ),
        "td": ParagraphStyle(
            "Td", parent=body, fontName=regular, fontSize=8.5, leading=11,
            spaceAfter=0,
        ),
        "td_b": ParagraphStyle(
            "TdB", parent=body, fontName=bold, fontSize=8.5, leading=11,
            textColor=colors.HexColor(INK), spaceAfter=0,
        ),
    }


def _rule(color: str = HAIRLINE, width: float = 0.6) -> HRFlowable:
    return HRFlowable(
        width="100%", thickness=width, color=colors.HexColor(color),
        spaceBefore=1, spaceAfter=5, lineCap="round",
    )


def _heading(title: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    return [Spacer(1, 6), Paragraph(esc(title), styles["h2"]), _rule()]


def _data_table(
    header: list[str],
    rows: list[list[Any]],
    fractions: list[float],
    styles: dict[str, ParagraphStyle],
    *,
    highlight: set[int] | None = None,
) -> Table:
    """Build a professional table whose cells are Unicode-font Paragraphs.

    Wrapping every cell in a Paragraph fixes the black-box glyphs the old raw
    string cells produced for Greek/Hebrew, and lets long cells wrap instead of
    overflowing. `highlight` shades those data-row indices.
    """
    col_widths = [f * CONTENT_W for f in fractions]
    head_cells = [Paragraph(esc(h), styles["th"]) for h in header]
    table_rows: list[list[Any]] = [head_cells]
    for row in rows:
        table_rows.append(
            [c if isinstance(c, Paragraph) else Paragraph(esc(c), styles["td"]) for c in row]
        )

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(SLATE)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(HAIRLINE)),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(SLATE)),
    ]
    for i in range(1, len(table_rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(ZEBRA)))
    for idx in highlight or set():
        r = idx + 1
        if r < len(table_rows):
            style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fff7ed")))
            style.append(("LINEBEFORE", (0, r), (0, r), 2, colors.HexColor("#b54708")))
    return Table(table_rows, colWidths=col_widths, style=TableStyle(style), hAlign="LEFT")


# ---------------------------------------------------------------------------
# Section blocks.
# ---------------------------------------------------------------------------


# Plain-English phrases keyed by the v3.1 axis values. The PDF reader
# sees prose, not taxonomy. The structured enums stay in the JSON for
# tooling; the badge translates them for a human eye.
_BREADTH_PHRASE = {
    "canon_wide": "Supported across the whole Bible",
    "broad": "Supported across many Bible texts",
    "partial": "Supported from a narrow set of texts",
    "thin": "Supported from sparse evidence",
}
_DIRECTNESS_PHRASE = {
    "direct": "Subject named directly in Scripture",
    "inferred": "Subject covered by a category in Scripture",
    "analogical": "Reached by general principle, not by a naming word",
    "silent": "Scripture does not engage the subject",
}
_STABILITY_PHRASE = {
    "stable": "Holds across manuscript variants",
    "sensitive": "Depends on a contested manuscript reading",
    "not_in_scope": "No NT manuscript apparatus applies",
}


def _axis_phrase(value: object, mapping: dict[str, str]) -> str:
    if isinstance(value, str) and value in mapping:
        return mapping[value]
    return ""


def _verdict_badge(evidence: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    verdict = evidence.get("verdict", {})
    color = _affirms_color(verdict.get("affirms"))
    label = Paragraph(
        f"<font color='{color}'>{esc(_affirms_label(verdict.get('affirms')))}</font>",
        styles["verdict_big"],
    )
    phrases = [
        _axis_phrase(verdict.get("lexical_breadth"), _BREADTH_PHRASE),
        _axis_phrase(verdict.get("lexical_directness"), _DIRECTNESS_PHRASE),
        _axis_phrase(verdict.get("variant_stability"), _STABILITY_PHRASE),
    ]
    body = "<br/>".join(esc(p) for p in phrases if p)
    meta = Paragraph(body or esc("verdict quality unavailable"), styles["verdict_meta"])
    return Table(
        [[label, meta]],
        colWidths=[CONTENT_W * 0.62, CONTENT_W * 0.38],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(BAND)),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 11),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBEFORE", (0, 0), (0, -1), 5, colors.HexColor(color)),
            ]
        ),
    )


def _statement_box(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    inner = Paragraph(esc(_bidi(text)), styles["statement"])
    return Table(
        [[inner]],
        colWidths=[CONTENT_W],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(INK)),
            ]
        ),
    )


def _lay_summary_block(text: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    return [*_heading("In plain language", styles), Paragraph(esc(_bidi(text)), styles["body"])]


def _dictionary_block(data: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    records = collect_strong_records(data)
    parts: list[Any] = _heading("Word dictionary", styles)
    if not records:
        parts.append(Paragraph("(no lexical terms referenced)", styles["small"]))
        return parts
    parts.append(
        Paragraph(
            "Every Hebrew and Greek word this study leans on, in everyday terms. "
            "Shaded rows are the anchor words the verdict rests on.",
            styles["small"],
        )
    )
    parts.append(Spacer(1, 3))

    header = ["Strong", "Word", "Sounds like", "Plain meaning", "Times in Bible"]
    rows: list[list[Any]] = []
    highlight: set[int] = set()
    for i, r in enumerate(records):
        if r["anchor"]:
            highlight.add(i)
        occ = f"{r['occurrences']:,}" if isinstance(r["occurrences"], int) else ""
        rows.append(
            [
                Paragraph(esc(r["strong"]), styles["td_b"]),
                Paragraph(esc(_bidi(r["lemma"])), styles["td"]),
                Paragraph(esc(r["translit"]), styles["td"]),
                Paragraph(esc(r["meaning"]) or "<font color='#94a3b8'>(no brief gloss)</font>", styles["td"]),
                Paragraph(esc(occ), styles["td"]),
            ]
        )
    parts.append(
        _data_table(header, rows, [0.12, 0.18, 0.20, 0.36, 0.14], styles, highlight=highlight)
    )
    parts.append(
        Paragraph(
            "Plain meanings: STEPBible brief lexicons TBESH (Hebrew) and TBESG (Greek), CC BY 4.0. "
            "Counts are occurrences across the 66-book canon.",
            styles["small"],
        )
    )
    return parts


def _verdict_block(verdict: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Verdict rationale", styles)
    parts.append(
        Paragraph(
            f"<b>Variant-robust:</b> {verdict.get('variant_robust')} "
            f"&nbsp;&middot;&nbsp; <b>Pan-canonical:</b> {verdict.get('pan_canonical')}",
            styles["body"],
        )
    )
    parts.append(Paragraph(esc(_bidi(verdict.get("rationale"))), styles["body"]))
    return parts


def _scripture_block(entries: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Scripture", styles)
    if not entries:
        parts.append(Paragraph("(none)", styles["small"]))
        return parts
    for s in entries:
        color = SUPPORTS_COLOR.get(s.get("supports", "neutral"), "#475467")
        figs = ", ".join(s.get("figures") or [])
        figs_str = f" &middot; figures: {esc(figs)}" if figs else ""
        terms = ", ".join(
            f"{esc(t.get('strong'))} {esc(_bidi(t.get('lemma')))}"
            for t in s.get("key_terms", [])
        )
        parts.append(
            KeepTogether(
                [
                    Paragraph(
                        f"<b>{esc(s.get('ref'))}</b> &middot; "
                        f"<font color='{color}'>{esc(s.get('supports'))}</font> &middot; "
                        f"genre: {esc(s.get('genre'))}{figs_str}",
                        styles["h3"],
                    ),
                    Paragraph(f"<b>Key terms.</b> {terms}", styles["body"]),
                    Paragraph(
                        f"<b>Reasoning.</b> {esc(_bidi(s.get('reasoning')))}", styles["body"]
                    ),
                    Spacer(1, 3),
                ]
            )
        )
    return parts


def _cross_refs_block(refs: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Cross references invoked", styles)
    if not refs:
        parts.append(Paragraph("(none)", styles["small"]))
        return parts
    rows = [
        [esc(r.get("from")), esc(r.get("to")), esc(r.get("source")), str(r.get("votes", ""))]
        for r in refs
    ]
    parts.append(_data_table(["From", "To", "Source", "Votes"], rows, [0.30, 0.30, 0.24, 0.16], styles))
    return parts


def _complicating_block(items: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Complicating texts", styles)
    if not items:
        parts.append(Paragraph("(none)", styles["small"]))
        return parts
    for c in items:
        addressed = c.get("addressed")
        badge = "addressed" if addressed else "unaddressed"
        color = "#1a7f37" if addressed else "#b42318"
        parts.append(
            KeepTogether(
                [
                    Paragraph(
                        f"<b>{esc(c.get('ref'))}</b> &middot; <font color='{color}'>{badge}</font>",
                        styles["h3"],
                    ),
                    Paragraph(esc(_bidi(c.get("resolution"))), styles["body"]),
                    Spacer(1, 3),
                ]
            )
        )
    return parts


def _concordance_block(traversed: list[str], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Concordance traversed", styles)
    if traversed:
        parts.append(Paragraph(", ".join(esc(t) for t in traversed), styles["body"]))
    else:
        parts.append(Paragraph("(empty; concordance-thin flag expected)", styles["small"]))
    return parts


def _variants_block(v: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Variants", styles)
    parts.append(
        Paragraph(
            f"<b>Verdict variant-sensitive:</b> {v.get('verdict_variant_sensitive')} "
            f"&nbsp;&middot;&nbsp; <b>ECM status:</b> {esc(v.get('ecm_status'))}",
            styles["body"],
        )
    )
    for u in v.get("variant_units_examined") or []:
        parts.append(
            Paragraph(
                f"<b>{esc(u.get('variant_id'))}</b> at {esc(u.get('ref'))}: "
                f"impact {esc(u.get('verdict_impact'))}. {esc(_bidi(u.get('note')))}",
                styles["body"],
            )
        )
    if v.get("note"):
        parts.append(Paragraph(esc(_bidi(v["note"])), styles["small"]))
    return parts


def _hermeneutics_block(h: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Hermeneutics", styles)
    parts.append(Paragraph(f"<b>Primary method.</b> {esc(h.get('primary_method'))}", styles["body"]))
    if h.get("frameworks_in_play"):
        parts.append(
            Paragraph(
                f"<b>Frameworks in play.</b> {esc(', '.join(h['frameworks_in_play']))}",
                styles["body"],
            )
        )
    flags = []
    if h.get("analogia_scripturae"):
        flags.append("analogia scripturae invoked")
    if h.get("progressive_revelation"):
        flags.append("progressive revelation factor")
    if flags:
        parts.append(Paragraph(" &middot; ".join(esc(f) for f in flags), styles["small"]))
    for clv in h.get("competing_lens_verdicts") or []:
        parts.append(
            Paragraph(
                f"<b>{esc(clv.get('framework'))}:</b> {esc(clv.get('verdict'))} "
                f"&middot; {esc(_bidi(clv.get('rationale')))}",
                styles["body"],
            )
        )
    if h.get("notes"):
        parts.append(Paragraph(esc(_bidi(h["notes"])), styles["body"]))
    return parts


def _stem_audit_block(s: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Stem audit", styles)
    if s.get("verdict_preloaded"):
        parts.append(
            Paragraph("<b><font color='#b54708'>verdict-preloaded: yes</font></b>", styles["body"])
        )
        if s.get("neutralized_form"):
            parts.append(Paragraph(f"<b>Neutralized form.</b> {esc(_bidi(s['neutralized_form']))}", styles["body"]))
    else:
        parts.append(Paragraph("verdict-preloaded: no", styles["small"]))
    if s.get("notes"):
        parts.append(Paragraph(esc(_bidi(s["notes"])), styles["small"]))
    return parts


def _citations_block(cites: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Citations", styles)
    if not cites:
        parts.append(Paragraph("(none)", styles["small"]))
        return parts
    rows = [
        [
            esc(c.get("type")),
            esc(c.get("source")),
            esc(c.get("license")),
            "yes" if c.get("redistribute") else "no",
            esc(c.get("ref")),
        ]
        for c in cites
    ]
    parts.append(
        _data_table(
            ["Type", "Source", "License", "Redist.", "Ref"],
            rows,
            [0.15, 0.31, 0.20, 0.13, 0.21],
            styles,
        )
    )
    return parts


def _license_audit_block(la: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    safe = la.get("evidence_safe_to_publish")
    color = "#1a7f37" if safe else "#b42318"
    label = "SAFE TO PUBLISH" if safe else "NOT SAFE TO PUBLISH"
    parts: list[Any] = _heading("License audit", styles)
    parts.append(Paragraph(f"<font color='{color}'><b>{label}</b></font>", styles["body"]))
    if la.get("non_redistributable_reason"):
        parts.append(Paragraph(f"<b>Reason.</b> {esc(la['non_redistributable_reason'])}", styles["body"]))
    sources = la.get("sources_used") or []
    if sources:
        rows = [
            [esc(s.get("source")), esc(s.get("license")), "yes" if s.get("redistribute") else "no"]
            for s in sources
        ]
        parts.append(_data_table(["Source", "License", "Redistribute"], rows, [0.50, 0.30, 0.20], styles))
    return parts


def _flags_block(flags: list[str], styles: dict[str, ParagraphStyle]) -> list[Any]:
    parts: list[Any] = _heading("Flags", styles)
    if not flags:
        parts.append(Paragraph("(none)", styles["small"]))
    else:
        parts.append(Paragraph(" &middot; ".join(f"<b>{esc(f)}</b>" for f in flags), styles["body"]))
    return parts


def build_story(
    data: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    question: dict[str, Any] | None,
) -> list[Any]:
    qid = data.get("id") or data.get("question_id") or "(unknown)"
    story: list[Any] = [
        Paragraph(esc(_humanize_id(qid)), styles["title"]),
        Paragraph(esc(qid), styles["tag"]),
    ]

    crumbs: list[str] = []
    if question:
        for key in ("category", "subcategory", "kind", "historical_consensus"):
            if question.get(key):
                crumbs.append(esc(question[key]))
        if question.get("brethren_distinctive"):
            crumbs.append("brethren distinctive")
    if crumbs:
        story.append(Paragraph(" &middot; ".join(crumbs), styles["subtitle"]))

    story.append(Spacer(1, 6))
    story.append(_verdict_badge(data, styles))
    story.append(Spacer(1, 8))

    if question and question.get("statement"):
        story.append(Paragraph("Statement under examination", styles["h3"]))
        story.append(_statement_box(question["statement"], styles))

    if data.get("lay_summary"):
        story.extend(_lay_summary_block(data["lay_summary"], styles))

    story.extend(_dictionary_block(data, styles))

    verdict = data.get("verdict", {})
    if verdict:
        story.extend(_verdict_block(verdict, styles))

    lex = data.get("lexical_evidence", {})
    if lex:
        story.extend(_scripture_block(lex.get("scripture") or [], styles))
        story.extend(_cross_refs_block(lex.get("cross_refs_invoked") or [], styles))
        story.extend(_complicating_block(lex.get("complicating_texts") or [], styles))
        story.extend(_concordance_block(lex.get("concordance_traversed") or [], styles))

    if data.get("variants"):
        story.extend(_variants_block(data["variants"], styles))
    if data.get("hermeneutics"):
        story.extend(_hermeneutics_block(data["hermeneutics"], styles))
    if data.get("stem_audit"):
        story.extend(_stem_audit_block(data["stem_audit"], styles))

    story.extend(_citations_block(data.get("citations") or [], styles))
    if data.get("license_audit"):
        story.extend(_license_audit_block(data["license_audit"], styles))
    story.extend(_flags_block(data.get("flags") or [], styles))
    return story


def render_pdf(
    json_path: Path,
    output_path: Path,
    font_pair: tuple[str, str],
    question: dict[str, Any] | None,
) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    styles = build_styles(*font_pair)
    qid = data.get("id") or data.get("question_id") or json_path.stem
    title = _humanize_id(qid)

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(font_pair[0], 7.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(MARGIN, 1.1 * cm, qid)
        canvas.drawRightString(PAGE_W - MARGIN, 1.1 * cm, f"Page {doc.page}")
        canvas.setStrokeColor(colors.HexColor(HAIRLINE))
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 1.45 * cm, PAGE_W - MARGIN, 1.45 * cm)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=title,
        author="christian-doctrine",
    )
    doc.build(build_story(data, styles, question), onFirstPage=on_page, onLaterPages=on_page)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Evidence JSON file(s). Defaults to every evidence/*.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the .pdf output. Defaults to alongside each input.",
    )
    args = parser.parse_args()

    inputs = list(args.inputs) if args.inputs else sorted(EVIDENCE_DIR.glob("*.json"))
    if not inputs:
        print(f"no JSON files found under {EVIDENCE_DIR}", file=sys.stderr)
        return 1

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    font_pair = register_unicode_font()
    questions = load_questions_index()

    for path in inputs:
        if not path.exists():
            print(f"skip: {path} does not exist", file=sys.stderr)
            continue
        out_dir = args.output_dir or path.parent
        out = out_dir / f"{path.stem}.pdf"
        question = questions.get(path.stem)
        try:
            render_pdf(path, out, font_pair, question)
        except Exception as exc:  # noqa: BLE001
            print(f"failed: {path.name}: {exc}", file=sys.stderr)
            continue
        print(f"wrote {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
