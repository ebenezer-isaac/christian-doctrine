"""Roman historians adapter (Tacitus, Suetonius, Pliny the Younger; Latin).

Pure Pipeline 1 adapter (h6_adapter_purity): parses ONLY the locally staged
Perseus TEI corpus under ``data/private/historical/roman-historians/latinLit/``.
No network, no subprocess, no dynamic import. Fetch and staging are separate
procurement steps.

Two TEI dialects live side by side in the Perseus latinLit tree, so this module
carries two extraction paths:

  * Tacitus Annals = TEI P4. ``<div1 type="book">`` holds an interleaved stream
    of ``<p>`` blocks and EMPTY ``<milestone unit="chapter"/>`` markers. A
    chapter is the text BETWEEN two consecutive milestones, not a subtree, so we
    slice the book stream on milestone boundaries.
  * Suetonius Lives and Pliny Letters = TEI P5 EpiDoc. Text lives in nested
    ``<div type="textpart" subtype="...">`` wrappers (chapter > section, or
    book > letter > section). Here the cited unit IS a subtree.

V1 scope is christian-relevant-only (docs/historical_data_inventory_catalog.json):
Tacitus Annals 15.43/44/45 (chapter level), Suetonius Claudius 25.3/4/5 and Nero
16.1/2/3 (section level), Pliny Ep 10.95/96/97 (letter level). Twelve chunks.

The license layer under ShareAlike is the Perseus TEI encoding; the underlying
editions (Fisher 1906, Ihm 1908) are PD by age. Every record carries the
CC-BY-SA-4.0 notice as a top-level field so downstream consumers cannot strip it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree as ET

from ingest.historical._common import HISTORICAL_DATA_ROOT, collapse_ws
from pipeline4.historical_schema import (
    ContestedInterpolation,
    HistoricalChunk,
    Provenance,
    WitnessSource,
)

SOURCE_SLUGS: tuple[str, ...] = ("tacitus", "suetonius", "pliny")

# Staged corpus root (data/private; adapter-pure path literal).
_LATIN_ROOT = HISTORICAL_DATA_ROOT / "roman-historians" / "latinLit"

_LICENSE = "CC-BY-SA-4.0"
_REDISTRIBUTE = True
_LICENSE_NOTE = (
    "Perseus Digital Library, Tufts University, CC-BY-SA-4.0. The underlying "
    "critical editions (Fisher Oxford 1906 Tacitus, Ihm Teubner 1908 Suetonius, "
    "Perseus lat1 Pliny) are public domain by age; the TEI encoding carries the "
    "ShareAlike obligation, which downstream sidecar JSON inherits."
)

# ---------------------------------------------------------------------------
# Per-source descriptors (work metadata + christian-relevant allowlist)
# ---------------------------------------------------------------------------

# Tacitus Annals (TEI P4 milestone). One file, one work.
_TACITUS_FILE = _LATIN_ROOT / "phi1351" / "phi005" / "phi1351.phi005.perseus-lat1.xml"
_TACITUS_BOOK = "15"
_TACITUS_CHAPTERS = ("43", "44", "45")

# Suetonius Lives (TEI P5 EpiDoc). One file per Life; section-level chunks.
_SUETONIUS_LIVES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    # (life-slug, life-title, abo-file-stem, christian-relevant chapter.section ids)
    ("claudius", "Divus Claudius", "abo015", ("25.3", "25.4", "25.5")),
    # Nero 16 in the staged Ihm Teubner edition has only sections 1 and 2 (no
    # 16.3 exists in this text). The Christian notice is in 16.2. We stay
    # data-faithful and do not fabricate a missing 16.3.
    ("nero", "Nero", "abo016", ("16.1", "16.2")),
)

# Pliny Letters (TEI P5 EpiDoc). One file, one work; letter-level chunks.
_PLINY_FILE = _LATIN_ROOT / "phi1318" / "phi001" / "phi1318.phi001.perseus-lat1.xml"
_PLINY_BOOK = "10"
_PLINY_LETTERS = ("95", "96", "97")


# ---------------------------------------------------------------------------
# TEI text cleaning
# ---------------------------------------------------------------------------

# Inline markup that must be folded to plain text or dropped before embedding.
_DROP_ELEMENTS = frozenset(
    {"note", "pb", "milestone", "head", "bibl", "ref", "gap", "del"}
)


def _local(tag: str) -> str:
    """Strip an XML namespace from a tag (``{ns}name`` -> ``name``)."""
    return tag.rsplit("}", 1)[-1]


def _element_text(elem: ET.Element) -> str:
    """Recursively collect visible text from a TEI element subtree.

    Drops editorial/apparatus elements (note, pb, milestone, head, del, ...),
    folds ``<add>`` insertions silently into the running text, and keeps the
    surface of every other element. Whitespace is normalized by the caller.
    """
    parts: list[str] = []

    def _walk(node: ET.Element) -> None:
        for child in node:
            name = _local(child.tag)
            if name in _DROP_ELEMENTS:
                # Skip the element and its subtree, but keep any tail text that
                # belongs to the parent flow after the dropped element.
                if child.tail:
                    parts.append(child.tail)
                continue
            if child.text:
                parts.append(child.text)
            _walk(child)
            if child.tail:
                parts.append(child.tail)

    if elem.text:
        parts.append(elem.text)
    _walk(elem)
    return "".join(parts)


def _clean(raw: str) -> str:
    return unicodedata.normalize("NFC", collapse_ws(raw))


# ---------------------------------------------------------------------------
# Tacitus (TEI P4 milestone slicer)
# ---------------------------------------------------------------------------

# The Perseus P4 Tacitus file is legacy SGML-ish XML; ElementTree parses it, but
# the milestone-slice approach is text-level (chapters are not subtrees), so we
# operate on the raw book markup rather than the parsed tree for chapter slicing.

_DIV1_BOOK_RE = re.compile(
    r'<div1\b[^>]*\btype="book"[^>]*\bn="(?P<n>[^"]+)"[^>]*>', re.IGNORECASE
)
_MILESTONE_RE = re.compile(
    r'<milestone\b[^>]*\bn="(?P<n>[^"]+)"[^>]*\bunit="chapter"[^>]*/?>', re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_MAP = {
    "&mdash;": " ",
    "&ndash;": " ",
    "&aelig;": "ae",
    "&AElig;": "Ae",
    "&oelig;": "oe",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
}


def _decode_entities(text: str) -> str:
    for ent, rep in _ENTITY_MAP.items():
        text = text.replace(ent, rep)
    # Numeric entities -> drop to space (rare in this corpus).
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    return text


def _tacitus_book_segment(xml: str, book: str) -> str:
    """Return the raw markup of the requested ``<div1 type="book">`` segment."""
    start = None
    for m in _DIV1_BOOK_RE.finditer(xml):
        if m.group("n") == book:
            start = m.end()
            break
    if start is None:
        raise ValueError(f"Tacitus book {book!r} not found in staged file")
    # The segment ends at the next div1 open or the closing </div1>.
    nxt = _DIV1_BOOK_RE.search(xml, start)
    end = nxt.start() if nxt else len(xml)
    return xml[start:end]


def _tacitus_chapter_text(book_seg: str, chapter: str) -> str:
    """Slice the text between milestone ``chapter`` and the next milestone."""
    milestones = list(_MILESTONE_RE.finditer(book_seg))
    if not milestones:
        raise ValueError("Tacitus book segment has no chapter milestones")
    for i, m in enumerate(milestones):
        if m.group("n") == chapter:
            text_start = m.end()
            text_end = (
                milestones[i + 1].start()
                if i + 1 < len(milestones)
                else len(book_seg)
            )
            raw = book_seg[text_start:text_end]
            raw = _decode_entities(raw)
            raw = _TAG_RE.sub(" ", raw)
            return _clean(raw)
    raise ValueError(f"Tacitus chapter milestone {chapter!r} not found")


def _parse_tacitus(path: Path | None = None) -> Iterator[HistoricalChunk]:
    xml = (path or _TACITUS_FILE).read_text(encoding="utf-8")
    book_seg = _tacitus_book_segment(xml, _TACITUS_BOOK)
    for chapter in _TACITUS_CHAPTERS:
        anchor = f"tacitus.annals.{_TACITUS_BOOK}.{chapter}"
        text = _tacitus_chapter_text(book_seg, chapter)
        # Annals 15.44 carries the Christianos/Chrestianos text-critical variant.
        if anchor == "tacitus.annals.15.44":
            contested = ContestedInterpolation(
                type="text-critical-variant",
                note=(
                    "Annals 15.44 reads 'Christianos' in Fisher Oxford 1906, the "
                    "edition staged here. The second Medicean manuscript "
                    "(Mediceus II) shows 'Chrestianos' altered to 'Christianos'; "
                    "Koestermann and Heubner discuss the variant. The text-critical "
                    "point does not affect the attestation that Tacitus names "
                    "Christus and Pontius Pilatus, but the manuscript reading is "
                    "contested. redact_for_embedding stays False: no span is "
                    "removed from the embedding surface."
                ),
                redact_for_embedding=False,
            )
        else:
            contested = ContestedInterpolation(type="none")
        yield HistoricalChunk(
            chunk_id=f"roman_historians.{anchor}.la",
            source_type="roman-historian",
            source=WitnessSource(
                source_slug="tacitus",
                work_id="tacitus.annals",
                work_title="Annals",
                author="Cornelius Tacitus",
                date_written_range="c. 116-117 CE",
                anchor_id=anchor,
                anchor_alt_citation=f"Annals {_TACITUS_BOOK}.{chapter}",
                language="la",
                translator=None,
                edition="Perseus TEI urn:cts:latinLit:phi1351.phi005.perseus-lat1 (Fisher Oxford 1906)",
            ),
            contested_interpolation=contested,
            provenance=Provenance(
                original_language="la",
                witness_chain=["latin-mediceus-ii", "fisher-oxford-1906", "perseus-tei-lat1"],
                extant_witnesses=["Mediceus II (Laurentianus 68.2)"],
                # Annals books 7-10 and the second half of book 16 are lost.
                loss_status="partial",
            ),
            text=text,
            text_to_embed=text,
            license=_LICENSE,
            redistribute=_REDISTRIBUTE,
            license_note=_LICENSE_NOTE,
        )


# ---------------------------------------------------------------------------
# Suetonius and Pliny (TEI P5 EpiDoc nested-div walker)
# ---------------------------------------------------------------------------


def _iter_textparts(elem: ET.Element, subtype: str) -> Iterator[ET.Element]:
    """Yield descendant ``<div type='textpart' subtype=SUBTYPE>`` elements."""
    for node in elem.iter():
        if _local(node.tag) != "div":
            continue
        if node.get("type") == "textpart" and node.get("subtype") == subtype:
            yield node


def _find_textpart(elem: ET.Element, subtype: str, n: str) -> ET.Element | None:
    for node in _iter_textparts(elem, subtype):
        if node.get("n") == n:
            return node
    return None


def _parse_suetonius(root_dir: Path | None = None) -> Iterator[HistoricalChunk]:
    base = root_dir or (_LATIN_ROOT / "phi1348")
    for life_slug, life_title, stem, ids in _SUETONIUS_LIVES:
        path = base / stem / f"phi1348.{stem}.perseus-lat2.xml"
        if not path.is_file():
            # Allow flat fixture layout: base/phi1348.<stem>.perseus-lat2.xml
            flat = base / f"phi1348.{stem}.perseus-lat2.xml"
            if flat.is_file():
                path = flat
        tree = ET.parse(path)
        root = tree.getroot()
        for cite in ids:
            chapter, section = cite.split(".")
            chap_elem = _find_textpart(root, "chapter", chapter)
            if chap_elem is None:
                raise ValueError(f"Suetonius {life_slug} chapter {chapter} not found")
            sec_elem = _find_textpart(chap_elem, "section", section)
            if sec_elem is None:
                raise ValueError(
                    f"Suetonius {life_slug} {chapter}.{section} section not found"
                )
            text = _clean(_element_text(sec_elem))
            anchor = f"suetonius.{life_slug}.{chapter}.{section}"
            yield HistoricalChunk(
                chunk_id=f"roman_historians.{anchor}.la",
                source_type="roman-historian",
                source=WitnessSource(
                    source_slug="suetonius",
                    work_id=f"suetonius.{life_slug}",
                    work_title=f"The Lives of the Twelve Caesars: {life_title}",
                    author="Gaius Suetonius Tranquillus",
                    date_written_range="c. 121 CE",
                    anchor_id=anchor,
                    anchor_alt_citation=f"{life_title} {chapter}.{section}",
                    language="la",
                    translator=None,
                    edition=(
                        "Perseus TEI urn:cts:latinLit:phi1348."
                        f"{stem}.perseus-lat2 (Ihm Teubner 1908)"
                    ),
                ),
                contested_interpolation=ContestedInterpolation(type="none"),
                provenance=Provenance(
                    original_language="la",
                    witness_chain=["ihm-teubner-1908", "perseus-tei-lat2"],
                    extant_witnesses=["Memmianus (Paris lat. 6115)", "Gudianus 268"],
                    loss_status="complete",
                ),
                text=text,
                text_to_embed=text,
                license=_LICENSE,
                redistribute=_REDISTRIBUTE,
                license_note=_LICENSE_NOTE,
            )


def _parse_pliny(path: Path | None = None) -> Iterator[HistoricalChunk]:
    tree = ET.parse(path or _PLINY_FILE)
    root = tree.getroot()
    book_elem = _find_textpart(root, "book", _PLINY_BOOK)
    if book_elem is None:
        raise ValueError(f"Pliny book {_PLINY_BOOK} not found")
    for letter in _PLINY_LETTERS:
        letter_elem = _find_textpart(book_elem, "letter", letter)
        if letter_elem is None:
            raise ValueError(f"Pliny Ep {_PLINY_BOOK}.{letter} not found")
        # Letter-level chunk: concatenate section text in document order.
        sections = list(_iter_textparts(letter_elem, "section"))
        if sections:
            text = _clean(" ".join(_element_text(s) for s in sections))
        else:
            text = _clean(_element_text(letter_elem))
        anchor = f"pliny.ep.{_PLINY_BOOK}.{letter}"
        yield HistoricalChunk(
            chunk_id=f"roman_historians.{anchor}.la",
            source_type="roman-historian",
            source=WitnessSource(
                source_slug="pliny",
                work_id="pliny.ep",
                work_title="Epistulae (Letters)",
                author="Gaius Plinius Caecilius Secundus",
                date_written_range="c. 111-113 CE",
                anchor_id=anchor,
                anchor_alt_citation=f"Ep. {_PLINY_BOOK}.{letter}",
                language="la",
                translator=None,
                edition="Perseus TEI urn:cts:latinLit:phi1318.phi001.perseus-lat1",
            ),
            contested_interpolation=ContestedInterpolation(type="none"),
            provenance=Provenance(
                original_language="la",
                witness_chain=["perseus-tei-lat1"],
                extant_witnesses=["Book 10 preserved via the Aldine tradition"],
                loss_status="complete",
            ),
            text=text,
            text_to_embed=text,
            license=_LICENSE,
            redistribute=_REDISTRIBUTE,
            license_note=_LICENSE_NOTE,
        )


# ---------------------------------------------------------------------------
# Adapter entry point
# ---------------------------------------------------------------------------


def parse() -> Iterator[HistoricalChunk]:
    """Yield the christian-relevant Latin chunks in a deterministic order.

    Order: Tacitus (3) then Suetonius (6) then Pliny (3) = 12 chunks. Stable
    across runs so two passes produce byte-identical JSONL (h5 determinism).
    """
    yield from _parse_tacitus()
    yield from _parse_suetonius()
    yield from _parse_pliny()
