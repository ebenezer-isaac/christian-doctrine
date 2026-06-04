"""Josephus (Perseus TEI) historical ingest adapter.

Parses the four surviving works of Flavius Josephus from the Perseus TEI P5
encoding (PerseusDL/canonical-greekLit, tlg0526) into one HistoricalChunk per
Niese section. Only the Whiston English translations (``perseus-eng2``) are
ingested; the Niese Greek (``perseus-grc2``) is present in the staged tree but
is not the primary index in v1.

Source mapping (verified against each work's __cts__.xml and root titles):

    tlg001 -> ant    Antiquities of the Jews        20 books, 1444 sections
    tlg002 -> vita   The Life of Flavius Josephus   flat (book defaults to 1)
    tlg003 -> apion  Against Apion                    2 books,   77 sections
    tlg004 -> wars   The Wars of the Jews             7 books,  707 sections

anchor_id = ``josephus.<work>.<book>.<niese_section>`` where ``<niese_section>``
is the section div's ``n`` attribute (the first Niese section the English block
spans). chunk_id == anchor_id.

Two source-specific disciplines per docs/HISTORICAL_SCHEMA.md and the catalog
required_flags:

  1. ``<note resp="editor">`` elements are 19th-century Whiston editorial
     commentary, NOT Josephus. They are excluded from chunk text entirely (text
     and tail of the note element are handled so surrounding prose is preserved).

  2. The Testimonium Flavianum at Antiquities 18.63 carries the universally
     bracketed clause "He was [the] Christ." The chunk sets
     contested_interpolation.type = "partial-interpolation" with
     redact_for_embedding = True; text_to_embed has that clause removed while
     text preserves it verbatim for citation honesty.

PURITY: this module reads only files under HISTORICAL_DATA_ROOT / "josephus".
No network, no subprocess, no dynamic import, no path literals outside
data/private/. Staging the Perseus files into data/private/historical/josephus/
is a separate procurement step performed outside this module.
"""

from __future__ import annotations

import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from ingest.historical._common import HISTORICAL_DATA_ROOT, collapse_ws
from pipeline4.historical_schema import (
    ContestedInterpolation,
    HistoricalChunk,
    Provenance,
    WitnessSource,
)

SOURCE_SLUGS: tuple[str, ...] = ("josephus",)

_TEI_NS = "{http://www.tei-c.org/ns/1.0}"

# Elements whose text content is editor overlay or empty markers and must not be
# blended into the source text. Their tail text (prose that follows the element)
# is preserved by the extractor.
_SKIP_ELEMENTS = frozenset({"note", "milestone", "pb", "lb"})

# tlg00X -> (work slug, full English work title, composition date range,
#            whether the work uses <div subtype="book"> in the English edition).
_WORKS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("tlg001", "ant", "Antiquities of the Jews", "93-94 CE", True),
    ("tlg002", "vita", "The Life of Flavius Josephus", "c. 99 CE", False),
    ("tlg003", "apion", "Against Apion", "c. 97 CE", True),
    ("tlg004", "wars", "The Wars of the Jews", "75-79 CE", True),
)

_AUTHOR = "Flavius Josephus"
_LANGUAGE = "en"
_TRANSLATOR = "William Whiston (1737)"
_LICENSE = "CC-BY-SA-4.0"
_REDISTRIBUTE = True
_LICENSE_NOTE = (
    "Perseus TEI encoding under CC-BY-SA-4.0; underlying Whiston translation is "
    "public domain by age. Sidecar JSON inherits the ShareAlike obligation."
)
_ORIGINAL_LANGUAGE = "el"
_WITNESS_CHAIN = ("greek-niese", "english-whiston-1737")
_EXTANT_WITNESSES = ("Niese 1885-1895 (codices A, M, V, W, R, P per work)",)
_LOSS_STATUS = "complete"

# Testimonium Flavianum: the single bracketed clause to remove from the
# embedding surface. Anchored to the exact Whiston wording in this edition.
_TF_ANCHOR = "josephus.ant.18.63"
_TF_CLAUSE = "He was [the] Christ."
_TF_NOTE = (
    "Antiquities 18.63 is the Testimonium Flavianum. The clause "
    '"He was [the] Christ" is universally bracketed by scholars as a later '
    "Christian interpolation; the surrounding passage is widely held to "
    "preserve an authentic Josephan core. The clause is removed from "
    "text_to_embed so retrieval does not surface the disputed prose, but it "
    "is preserved verbatim in text for citation honesty."
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _section_text(section: ET.Element) -> str:
    """Return the visible source text of a section div.

    Excludes <note resp="editor"> (Whiston commentary) and empty structural
    markers (milestone, pb, lb) entirely, while preserving the tail text that
    follows each excluded element so the surrounding prose stays intact.
    Whitespace is collapsed; the result is NFC-normalized.
    """
    parts: list[str] = []

    def _walk(el: ET.Element) -> None:
        if _local(el.tag) in _SKIP_ELEMENTS:
            if el.tail:
                parts.append(el.tail)
            return
        if el.text:
            parts.append(el.text)
        for child in el:
            _walk(child)
        if el.tail:
            parts.append(el.tail)

    if section.text:
        parts.append(section.text)
    for child in section:
        _walk(child)

    return unicodedata.normalize("NFC", collapse_ws("".join(parts)))


_WORK_LABEL = {"ant": "Ant", "vita": "Vita", "apion": "Apion", "wars": "Wars"}


def _section_milestones(section: ET.Element) -> tuple[str | None, str | None]:
    """Return (Whiston_chapter, Whiston_section) declared inside this section.

    A section declares a Whiston_chapter milestone only when it is the first
    section of a new Whiston chapter; later sections of the same chapter carry
    only a Whiston_section milestone. The caller carries the chapter forward.
    """
    chapter: str | None = None
    sect: str | None = None
    for el in section.iter():
        if _local(el.tag) != "milestone":
            continue
        unit = el.get("unit")
        if unit == "Whiston_chapter":
            chapter = el.get("n")
        elif unit == "Whiston_section":
            sect = el.get("n")
    return chapter, sect


def _whiston_citation(
    work: str, book_n: str, chapter: str | None, sect: str | None, has_books: bool
) -> str | None:
    """Build the Whiston citation for citation parity with classic apologetics.

    Form for works with books: ``Ant 18.3.3 (Whiston)`` (book.chapter.section).
    Vita has no books, so the book segment is omitted: ``Vita 1 (Whiston)``.
    Returns None when no Whiston milestone is present in the section.
    """
    # Whiston preface chapters are encoded as the token "pr."; strip the
    # trailing period so a joined citation does not produce a double dot.
    norm_chapter = chapter.rstrip(".") if chapter is not None else None
    tail = [p for p in (norm_chapter, sect) if p]
    if not tail:
        return None
    pieces = ([book_n] if has_books else []) + tail
    return f"{_WORK_LABEL[work]} {'.'.join(pieces)} (Whiston)"


def _edition_urn(tlg: str) -> str:
    return f"urn:cts:greekLit:tlg0526.{tlg}.perseus-eng2"


def _parse_work(
    xml_path: Path,
    tlg: str,
    work: str,
    work_title: str,
    date_range: str,
    has_books: bool,
) -> Iterator[HistoricalChunk]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    body = root.find(f".//{_TEI_NS}text/{_TEI_NS}body")
    if body is None:
        return
    translation = body.find(f"{_TEI_NS}div")
    if translation is None:
        return

    if has_books:
        book_iter = (
            (b.get("n") or "1", b)
            for b in translation.findall(f"{_TEI_NS}div[@subtype='book']")
        )
    else:
        # Vita has no book divs in the English edition; treat the whole work as
        # a single book numbered 1.
        book_iter = (("1", translation),)

    work_id = f"josephus.{work}"
    edition = _edition_urn(tlg)

    for book_n, book_el in book_iter:
        # Whiston chapter is declared once at the first section of each chapter
        # and carried forward to subsequent sections within the same book.
        current_chapter: str | None = None
        for sec in book_el.findall(f"{_TEI_NS}div[@subtype='section']"):
            section_n = sec.get("n")
            if section_n is None:
                continue
            declared_chapter, whiston_section = _section_milestones(sec)
            if declared_chapter is not None:
                current_chapter = declared_chapter
            anchor_id = f"josephus.{work}.{book_n}.{section_n}"
            text = _section_text(sec)
            if not text:
                continue

            if anchor_id == _TF_ANCHOR:
                contested = ContestedInterpolation(
                    type="partial-interpolation",
                    note=_TF_NOTE,
                    redact_for_embedding=True,
                )
                redacted = unicodedata.normalize(
                    "NFC", collapse_ws(text.replace(_TF_CLAUSE, ""))
                )
                if redacted == text:
                    # Defensive: if the exact clause string ever drifts the
                    # adapter must fail loudly rather than ship an inconsistent
                    # redaction (schema rule 10 would reject it anyway).
                    raise ValueError(
                        "Testimonium Flavianum clause not found for redaction at "
                        f"{anchor_id}; expected {_TF_CLAUSE!r}"
                    )
                text_to_embed = redacted
            else:
                contested = ContestedInterpolation()
                text_to_embed = text

            yield HistoricalChunk(
                chunk_id=anchor_id,
                source_type="jewish-historian",
                source=WitnessSource(
                    source_slug="josephus",
                    work_id=work_id,
                    work_title=work_title,
                    author=_AUTHOR,
                    date_written_range=date_range,
                    anchor_id=anchor_id,
                    anchor_alt_citation=_whiston_citation(
                        work, book_n, current_chapter, whiston_section, has_books
                    ),
                    language=_LANGUAGE,
                    translator=_TRANSLATOR,
                    edition=edition,
                ),
                contested_interpolation=contested,
                provenance=Provenance(
                    original_language=_ORIGINAL_LANGUAGE,
                    witness_chain=list(_WITNESS_CHAIN),
                    extant_witnesses=list(_EXTANT_WITNESSES),
                    loss_status=_LOSS_STATUS,
                ),
                text=text,
                text_to_embed=text_to_embed,
                license=_LICENSE,
                redistribute=_REDISTRIBUTE,
                license_note=_LICENSE_NOTE,
            )


def parse() -> Iterator[HistoricalChunk]:
    """Parse the four English Josephus works in deterministic order.

    Order is fixed by _WORKS (ant, vita, apion, wars), then by document order of
    book and section divs within each work, so two runs produce a byte-identical
    josephus.jsonl.
    """
    root = HISTORICAL_DATA_ROOT / "josephus"
    for tlg, work, work_title, date_range, has_books in _WORKS:
        xml_path = root / tlg / f"tlg0526.{tlg}.perseus-eng2.xml"
        if not xml_path.is_file():
            continue
        yield from _parse_work(
            xml_path, tlg, work, work_title, date_range, has_books
        )
