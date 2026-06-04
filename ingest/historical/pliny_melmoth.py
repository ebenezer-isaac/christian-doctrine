"""Pliny the Younger, English translation (William Melmoth, 1746).

Pure Pipeline 1 adapter (h6_adapter_purity): parses ONLY the locally staged
Melmoth text under ``data/private/historical/roman-historians/melmoth/``. No
network, no subprocess, no dynamic import. The fetch (Wikisource / Project
Gutenberg) and staging are separate procurement steps.

The Perseus latinLit tree ships Pliny in Latin only, so the English column for
the Trajan correspondence is supplied here by the public-domain Melmoth 1746
translation (revised by F. C. T. Bosanquet). V1 scope is the two christian
-relevant letters: Pliny to Trajan on the Christians (Ep 10.96) and Trajan's
reply (Ep 10.97).

These English chunks deliberately carry the SAME ``anchor_id`` as the Latin
chunks emitted by ``roman_historians.py`` (``pliny.ep.10.96`` and
``pliny.ep.10.97``) so Pipeline 4 can join the Latin and English witnesses on
``anchor_id``. The ``chunk_id`` differs (``.en`` suffix) so the two records do
not collide in the HistoricalChunk uniqueness constraint.

Melmoth's own letter numbering (XCVII, XCVIII) is offset by one from the modern
canonical Latin numbering; the staged source file is annotated with the
canonical Ep 10.96 / 10.97 mapping and this parser keys on that annotation.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path

from ingest.historical._common import HISTORICAL_DATA_ROOT, collapse_ws
from pipeline4.historical_schema import (
    ContestedInterpolation,
    HistoricalChunk,
    Provenance,
    WitnessSource,
)

SOURCE_SLUGS: tuple[str, ...] = ("pliny",)

_MELMOTH_FILE = (
    HISTORICAL_DATA_ROOT
    / "roman-historians"
    / "melmoth"
    / "pliny_ep_10_melmoth.txt"
)

_LICENSE = "PD"
_REDISTRIBUTE = True
_LICENSE_NOTE = (
    "William Melmoth (1746) translation, revised by F. C. T. Bosanquet; public "
    "domain by age (translator died 1799). Staged from Project Gutenberg eBook "
    "2811. Wikisource does not host the Melmoth translation directly."
)
_EDITION = "Project Gutenberg eBook 2811 (Melmoth 1746, rev. Bosanquet)"

# Letter markers placed in the staged source file during procurement. Each marks
# the start of one letter body; the body runs to the next marker or EOF.
_LETTER_MARK_RE = re.compile(
    r"^###\s+LETTER\s+Ep\s+(?P<book>\d+)\.(?P<letter>\d+)\b[^\n]*$",
    re.MULTILINE,
)

# Trailing footnote reference markers like [1066] or superscript [1].
_FOOTNOTE_RE = re.compile(r"\[\d+\]")
# The Melmoth section header line inside each body (e.g. "XCVII To THE EMPEROR").
_HEADER_LINE_RE = re.compile(r"^[IVXLC]+\b[^\n]*$", re.MULTILINE)


def _clean_body(raw: str) -> str:
    """Strip the Melmoth header line and footnote markers, normalize text."""
    # Drop footnote reference markers.
    text = _FOOTNOTE_RE.sub("", raw)
    # Split into paragraphs on blank lines; drop the leading roman-numeral
    # header line (the body's first non-empty line), keep the prose.
    paras = re.split(r"\n\s*\n", text)
    cleaned: list[str] = []
    header_dropped = False
    for para in paras:
        collapsed = collapse_ws(para)
        if not collapsed:
            continue
        if not header_dropped:
            # The first non-empty paragraph is the Melmoth roman-numeral header
            # line ("XCVII To THE EMPEROR TRAJAN"); drop it once, then keep prose.
            header_dropped = True
            if _HEADER_LINE_RE.match(para.strip()):
                continue
        cleaned.append(collapsed)
    joined = "\n\n".join(cleaned)
    return unicodedata.normalize("NFC", joined)


# Per-letter metadata for the two christian-relevant Trajan-correspondence letters.
_LETTER_META: dict[str, dict[str, str]] = {
    "96": {
        "alt": "Ep. 10.96 (Melmoth XCVII)",
        "chain": "pliny to trajan",
    },
    "97": {
        "alt": "Ep. 10.97 (Melmoth XCVIII)",
        "chain": "trajan to pliny",
    },
}

# V1 scope: only Ep 10.96 and 10.97 in English (the Christian letters).
_WANTED = ("96", "97")
_WANTED_BOOK = "10"


def _read_letters(path: Path | None = None) -> dict[str, str]:
    """Return {letter_number: cleaned_body} for the staged Melmoth letters."""
    raw = (path or _MELMOTH_FILE).read_text(encoding="utf-8")
    marks = list(_LETTER_MARK_RE.finditer(raw))
    if not marks:
        raise ValueError("no '### LETTER Ep B.L' markers in staged Melmoth file")
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        if m.group("book") != _WANTED_BOOK:
            continue
        body_start = m.end()
        body_end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
        out[m.group("letter")] = _clean_body(raw[body_start:body_end])
    return out


def parse(path: Path | None = None) -> Iterator[HistoricalChunk]:
    """Yield the two English (Melmoth) chunks in deterministic letter order.

    Anchors match the Latin chunks (pliny.ep.10.96 / .97); chunk_id uses an
    ``.en`` suffix so the English witness joins the Latin witness on anchor_id
    without colliding on chunk_id.
    """
    bodies = _read_letters(path)
    for letter in _WANTED:
        text = bodies.get(letter)
        if not text:
            raise ValueError(f"Melmoth Ep {_WANTED_BOOK}.{letter} body is empty")
        anchor = f"pliny.ep.{_WANTED_BOOK}.{letter}"
        meta = _LETTER_META[letter]
        yield HistoricalChunk(
            chunk_id=f"pliny_melmoth.{anchor}.en",
            source_type="roman-historian",
            source=WitnessSource(
                source_slug="pliny",
                work_id="pliny.ep",
                work_title="Epistulae (Letters)",
                author="Gaius Plinius Caecilius Secundus",
                date_written_range="c. 111-113 CE",
                anchor_id=anchor,
                anchor_alt_citation=meta["alt"],
                language="en",
                translator="William Melmoth (1746)",
                edition=_EDITION,
            ),
            contested_interpolation=ContestedInterpolation(type="none"),
            provenance=Provenance(
                original_language="la",
                witness_chain=["latin-original", "melmoth-1746", "bosanquet-rev"],
                extant_witnesses=["Book 10 preserved via the Aldine tradition"],
                loss_status="complete",
            ),
            text=text,
            text_to_embed=text,
            license=_LICENSE,
            redistribute=_REDISTRIBUTE,
            license_note=_LICENSE_NOTE,
        )
