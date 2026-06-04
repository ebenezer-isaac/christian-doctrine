"""OT Pseudepigrapha (R. H. Charles, 1913 / 1917) Pipeline 1 historical adapter.

Emits ``HistoricalChunk`` records for the second-temple Jewish literature that
Charles collected. Seven works are in scope (the schema's ``second-temple-
literature`` block):

    1enoch  jubilees  test12  2baruch  4ezra  pssol  sibor

This adapter is PURE: it reads only local files under
``data/private/historical/pseudepigrapha/<work>/`` and performs no network,
subprocess, or dynamic import. Fetching the upstream HTML is a separate
Pipeline 1 procurement step (a Bash ``curl`` run by the orchestrator).

Per-work source format and chunk granularity follow the chunking strategy in
docs/HISTORICAL_SCHEMA.md:

    1enoch   sacred-texts BOE chapter files (boe004.htm..boe112.htm); UTF-8;
             Charles' critical ceiling-bracket apparatus U+2308 / U+2309 is
             preserved verbatim in ``text`` and stripped from ``text_to_embed``.
             Granularity: one chunk per verse (poetic). Jude 14-15 cites
             1 Enoch 1.9, so 1enoch.1.9 is always emitted as its own atomic
             chunk.
    jubilees CCEL per-chapter files (1.htm..50.htm). Each <li> in the chapter
             <ol> is a Charles verse; the chapter is narrative prose, so the
             chunk granularity is one chunk per chapter (verses joined).
    test12   earlychristianwritings single page (all twelve testaments). Bold
             chapter headings, inline verse digits. Narrative prose, so one
             chunk per chapter. The work is a known Christianized recension, so
             every chunk carries contested_interpolation.type="recension-layer"
             and explicit Jesus-naming clauses (bracketed in Charles) are
             redacted from text_to_embed.
    sibor    Wikisource APOT Volume II Sibylline Oracles page. Charles includes
             only the Jewish strata (Books III, IV, V). Parenthetical (N) line
             markers; poetic, clustered into ~6-line strophes.

Works 2baruch, 4ezra and pssol are NOT emitted: no clean-license Charles 1913
machine-readable transcription was obtainable via a static HTTP pull during
procurement (Wikisource APOT Volume II transcribes only the Sibylline Oracles;
the standalone Wikisource "Psalms of Solomon" page is a community Translation,
not the PD Charles/Gray text). They are listed in SOURCE_SLUGS so the contract
is stable; the adapter skips any work whose source directory is absent, so the
three can be dropped in later without code changes.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path

from ingest.historical._common import HISTORICAL_DATA_ROOT
from pipeline4.historical_schema import (
    ContestedInterpolation,
    HistoricalChunk,
    Provenance,
    WitnessSource,
)

# Deterministic order: this tuple fixes the work-emission order in parse().
SOURCE_SLUGS: tuple[str, ...] = (
    "1enoch",
    "jubilees",
    "test12",
    "2baruch",
    "4ezra",
    "pssol",
    "sibor",
)

_ROOT = HISTORICAL_DATA_ROOT / "pseudepigrapha"

SOURCE_TYPE = "second-temple-literature"
LICENSE = "PD"
REDISTRIBUTE = True
LANGUAGE = "en"
TRANSLATOR = "R. H. Charles (1913)"

# Charles' critical apparatus brackets (restored / conjectural / doubtful
# readings). Preserved verbatim in ``text``; stripped for ``text_to_embed``.
_CEILING_OPEN = "⌈"  # left ceiling
_CEILING_CLOSE = "⌉"  # right ceiling

# Per-work static metadata. date_written_range and provenance follow the
# Historical Attestation Schema guidance; author is None (pseudonymous).
_WORK_META: dict[str, dict[str, object]] = {
    "1enoch": {
        "work_title": "1 Enoch (Ethiopic Book of Enoch)",
        "date_written_range": "c. 300 BCE to 100 BCE",
        "edition": "Charles 1917 (sacred-texts.com BOE chapter HTML)",
        "original_language": "arc",
        "witness_chain": [
            "aramaic-qumran-4q201-212",
            "greek-codex-panopolitanus",
            "ethiopic",
            "english-charles-1913",
        ],
        "extant_witnesses": [
            "4Q201-4Q212 (Aramaic)",
            "Codex Panopolitanus (Greek)",
            "Ethiopic MSS (Charles' base)",
        ],
        "loss_status": "complete-in-ethiopic",
    },
    "jubilees": {
        "work_title": "The Book of Jubilees",
        "date_written_range": "c. 160 BCE to 150 BCE",
        "edition": "Charles 1913 APOT vol II (CCEL per-chapter HTML)",
        "original_language": "he",
        "witness_chain": [
            "hebrew-qumran-fragments",
            "greek-lost",
            "ethiopic",
            "english-charles-1913",
        ],
        "extant_witnesses": [
            "4Q216-4Q228 (Hebrew fragments)",
            "Ethiopic MSS (Charles' base)",
        ],
        "loss_status": "complete-in-ethiopic",
    },
    "test12": {
        "work_title": "The Testaments of the Twelve Patriarchs",
        "date_written_range": "c. 150 BCE Jewish stratum; 2nd century CE Christian recension",
        "edition": "Charles 1913 APOT vol II (earlychristianwritings.com transcription)",
        "original_language": "el",
        "witness_chain": [
            "hebrew-aramaic-jewish-stratum-partly-lost",
            "greek-christianized-recension",
            "english-charles-1913",
        ],
        "extant_witnesses": [
            "Greek MSS (Charles' base, Christianized recension)",
            "Aramaic Levi fragments (Qumran, Cairo Geniza)",
        ],
        "loss_status": "partial",
    },
    "sibor": {
        "work_title": "The Sibylline Oracles (Jewish strata: Books III, IV, V)",
        "date_written_range": "c. 160 BCE to 100 CE (Jewish books)",
        "edition": "Charles 1913 APOT vol II (Wikisource transcription; Lanchester tr.)",
        "original_language": "el",
        "witness_chain": ["greek", "english-charles-1913"],
        "extant_witnesses": ["Greek Sibylline MSS (omega, phi, psi groups)"],
        "loss_status": "complete",
    },
}

_WS_RE = re.compile(r"[ \t\r\n ]+")
_TAG_RE = re.compile(r"<[^>]+>")
_PAGE_ANCHOR_RE = re.compile(r"<a\s+name=\"page_\d+\">.*?</a>", re.IGNORECASE | re.DOTALL)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _clean_text(raw_fragment: str) -> str:
    """Strip tags and entities from an HTML fragment, collapse whitespace.

    Ceiling-bracket characters that arrive as numeric entities (&#x2308;) are
    decoded by ``_html.unescape`` and survive into the result.
    """
    text = _PAGE_ANCHOR_RE.sub(" ", raw_fragment)
    text = _BR_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    # Tidy the spacing Charles' inline bracket spans introduce, e.g.
    # "elect ⌈⌈ and ⌉⌉ righteous" -> keep brackets but trim
    # the stray spaces immediately inside them so the bracketed token reads
    # naturally while staying verbatim in content.
    text = re.sub(rf"{_CEILING_OPEN}\s+", _CEILING_OPEN, text)
    text = re.sub(rf"\s+{_CEILING_CLOSE}", _CEILING_CLOSE, text)
    return text


def _strip_ceiling(text: str) -> str:
    """Remove Charles' critical ceiling brackets for the embedding surface."""
    out = text.replace(_CEILING_OPEN, "").replace(_CEILING_CLOSE, "")
    return _WS_RE.sub(" ", out).strip()


def _make_chunk(
    work: str,
    anchor_tail: str,
    text: str,
    *,
    contested: ContestedInterpolation,
    text_to_embed: str | None = None,
) -> HistoricalChunk:
    meta = _WORK_META[work]
    anchor = f"{work}.{anchor_tail}"
    body = _nfc(text)
    embed = _nfc(text_to_embed) if text_to_embed is not None else _nfc(_strip_ceiling(text))
    if not embed:
        embed = body
    source = WitnessSource(
        source_slug=work,
        work_id=work,
        work_title=str(meta["work_title"]),
        author=None,
        date_written_range=str(meta["date_written_range"]),
        anchor_id=anchor,
        anchor_alt_citation=None,
        language=LANGUAGE,
        translator=TRANSLATOR,
        edition=str(meta["edition"]),
    )
    provenance = Provenance(
        original_language=str(meta["original_language"]),
        witness_chain=list(meta["witness_chain"]),  # type: ignore[arg-type]
        extant_witnesses=list(meta["extant_witnesses"]),  # type: ignore[arg-type]
        loss_status=str(meta["loss_status"]),  # type: ignore[arg-type]
    )
    return HistoricalChunk(
        chunk_id=anchor,
        source_type=SOURCE_TYPE,
        source=source,
        contested_interpolation=contested,
        provenance=provenance,
        text=body,
        text_to_embed=embed,
        license=LICENSE,
        redistribute=REDISTRIBUTE,
        license_note="Charles 1913/1917 APOT; PD by age (author d.1931, pub. pre-1929).",
    )


def _none_contested() -> ContestedInterpolation:
    return ContestedInterpolation(type="none", note=None, redact_for_embedding=False)


# ---------------------------------------------------------------------------
# 1 Enoch  (sacred-texts BOE chapter HTML; one chunk per verse)
# ---------------------------------------------------------------------------

_ENOCH_CH_RE = re.compile(r"CHAPTER\s+[IVXLC]+\.?\s*</h3>", re.IGNORECASE)
_VERSE_MARKER_RE = re.compile(r"(?:(?<=\s)|^)(\d{1,3})\.\s")


def _enoch_body(raw: str) -> str | None:
    m = _ENOCH_CH_RE.search(raw)
    if not m:
        return None
    body = raw[m.end():]
    # Footer navigation begins with a <center> block; cut there.
    cut = body.lower().find("<center")
    if cut > 0:
        body = body[:cut]
    return _clean_text(body)


def _split_enoch_verses(body: str) -> list[tuple[str, str]]:
    """Split a 1 Enoch chapter body into (verse_label, text) pairs.

    Charles numbers verses as ``N.`` inline. Some short chapters carry a single
    unnumbered verse; leading prose before the first marker is attached to the
    first verse. Duplicate verse numbers (e.g. the two-column manuscript-variant
    chapters) are disambiguated with sub-verse letters so every anchor is unique.
    """
    matches = list(_VERSE_MARKER_RE.finditer(body))
    if not matches:
        return [("1", body)] if body else []
    spans: list[tuple[int, str]] = []
    lead = body[: matches[0].start()].strip()
    for i, mt in enumerate(matches):
        num = int(mt.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        spans.append((num, body[mt.end():end].strip()))
    if lead:
        first_num, first_txt = spans[0]
        spans[0] = (first_num, (lead + " " + first_txt).strip())
    out: list[tuple[str, str]] = []
    seen: dict[int, int] = {}
    for num, txt in spans:
        if not txt:
            continue
        if num in seen:
            seen[num] += 1
            label = f"{num}{chr(ord('a') + seen[num])}"
        else:
            seen[num] = 0
            label = str(num)
        out.append((label, txt))
    return out


def _parse_enoch(work_dir: Path) -> Iterator[HistoricalChunk]:
    files = sorted(
        work_dir.glob("boe*.htm"),
        key=lambda p: int(re.search(r"boe(\d+)", p.name).group(1)),  # type: ignore[union-attr]
    )
    for path in files:
        file_num = int(re.search(r"boe(\d+)", path.name).group(1))  # type: ignore[union-attr]
        chapter = file_num - 3  # boe004.htm == chapter 1
        if chapter < 1:
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        body = _enoch_body(raw)
        if not body:
            continue
        for label, text in _split_enoch_verses(body):
            yield _make_chunk(
                "1enoch", f"{chapter}.{label}", text, contested=_none_contested()
            )


# ---------------------------------------------------------------------------
# Jubilees  (CCEL per-chapter HTML; one chunk per chapter, narrative prose)
# ---------------------------------------------------------------------------

_JUB_CHAP_RE = re.compile(r"\[Chapter\s+(\d+)\]", re.IGNORECASE)
_JUB_OL_RE = re.compile(r"<ol>(.*?)</ol>", re.IGNORECASE | re.DOTALL)
_JUB_LI_RE = re.compile(r"<li>", re.IGNORECASE)


def _parse_jubilees(work_dir: Path) -> Iterator[HistoricalChunk]:
    files = sorted(
        work_dir.glob("*.htm"),
        key=lambda p: int(re.search(r"(\d+)\.htm", p.name).group(1)),  # type: ignore[union-attr]
    )
    for path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        cm = _JUB_CHAP_RE.search(raw)
        if not cm:
            continue
        chapter = int(cm.group(1))
        om = _JUB_OL_RE.search(raw, cm.end())
        if not om:
            continue
        items = _JUB_LI_RE.split(om.group(1))[1:]
        verses: list[str] = []
        for item in items:
            cleaned = _clean_text(item)
            if cleaned:
                verses.append(cleaned)
        if not verses:
            continue
        # Narrative prose: one chunk per chapter, verses joined and numbered so
        # the verse boundaries Charles printed are recoverable.
        joined = " ".join(f"{i}. {v}" for i, v in enumerate(verses, 1))
        yield _make_chunk(
            "jubilees", f"{chapter}.1", joined, contested=_none_contested()
        )


# ---------------------------------------------------------------------------
# Testaments of the Twelve Patriarchs  (ECW single page; chunk per chapter)
# ---------------------------------------------------------------------------

_T12_PATRIARCHS: tuple[str, ...] = (
    "reuben",
    "simeon",
    "levi",
    "judah",
    "issachar",
    "zebulun",
    "dan",
    "naphtali",
    "gad",
    "asher",
    "joseph",
    "benjamin",
)
_T12_HEAD_RE = re.compile(r"THE TESTAMENT OF ([A-Z]+)")
_T12_FOOTER_RE = re.compile(r"Historical Jesus Theories|Kirby, Peter")
_T12_CHAP_RE = re.compile(r"<P>\s*<B>\s*(\d+)\s*</B>", re.IGNORECASE)

# Charles brackets the second-century Christian-recension insertions. The
# explicit Jesus-naming clauses are isolated by these bracketed phrases; they
# are removed from text_to_embed so retrieval does not surface the disputed
# prose, while the verbatim text is preserved in ``text`` for citation honesty.
_T12_REDACT_RE = re.compile(
    r"\[[^\]]*(?:Saviour of the world|Lamb of God|Jesus|Christ|"
    r"only[- ]begotten|the cross|crucif)[^\]]*\]",
    re.IGNORECASE,
)

_T12_RECENSION_NOTE = (
    "The Testaments of the Twelve Patriarchs survive as a Christianized Greek "
    "recension of a Jewish original. Charles' introduction identifies the "
    "Levi-Judah priest-king messianism and the explicit naming of the Saviour "
    "as second-century CE Christian insertions over the Jewish stratum. "
    "Explicit Jesus-naming clauses are redacted from the embedding surface."
)


def _parse_test12(work_dir: Path) -> Iterator[HistoricalChunk]:
    candidates = list(work_dir.glob("*.html")) + list(work_dir.glob("*.htm"))
    if not candidates:
        return
    path = sorted(candidates)[0]
    raw = path.read_text(encoding="utf-8", errors="replace")
    start = _T12_HEAD_RE.search(raw)
    if not start:
        return
    footer = _T12_FOOTER_RE.search(raw)
    region = raw[start.start(): footer.start() if footer else len(raw)]
    heads = list(_T12_HEAD_RE.finditer(region))
    for hi, head in enumerate(heads):
        name = head.group(1).lower()
        if name not in _T12_PATRIARCHS:
            continue
        block_end = heads[hi + 1].start() if hi + 1 < len(heads) else len(region)
        block = region[head.end():block_end]
        chaps = list(_T12_CHAP_RE.finditer(block))
        # The earlychristianwritings transcription mislabels one Testament of
        # Judah chapter (it prints "26" twice and omits "25"). The chapter token
        # must stay numeric to satisfy the anchor pattern, so a repeated chapter
        # is disambiguated with a sub-verse letter on the verse component rather
        # than by renumbering the chapter (which would alter the source reading).
        seen_chapters: dict[str, int] = {}
        for ci, ch in enumerate(chaps):
            chapter = ch.group(1)
            c_end = chaps[ci + 1].start() if ci + 1 < len(chaps) else len(block)
            chap_text = _clean_text(block[ch.end():c_end])
            if not chap_text:
                continue
            if chapter in seen_chapters:
                seen_chapters[chapter] += 1
                verse_label = f"1{chr(ord('a') + seen_chapters[chapter])}"
            else:
                seen_chapters[chapter] = 0
                verse_label = "1"
            redacted = _T12_REDACT_RE.sub("", chap_text)
            redacted = _WS_RE.sub(" ", redacted).strip()
            has_naming = redacted != chap_text and bool(redacted)
            contested = ContestedInterpolation(
                type="recension-layer",
                note=_T12_RECENSION_NOTE,
                redact_for_embedding=has_naming,
            )
            embed = redacted if has_naming else None
            yield _make_chunk(
                "test12",
                f"{name}.{chapter}.{verse_label}",
                chap_text,
                contested=contested,
                text_to_embed=embed,
            )


# ---------------------------------------------------------------------------
# Sibylline Oracles  (Wikisource; Books III, IV, V; strophe clusters)
# ---------------------------------------------------------------------------

_SIBOR_BOOKS: tuple[tuple[str, str, str], ...] = (
    # (chapter_number, this_book_anchor, next_book_anchor or "")
    ("3", "III", "IV"),
    ("4", "IV", "V"),
    ("5", "V", ""),
)
_SIBOR_STROPHE_SIZE = 6
_SIBOR_SUP_RE = re.compile(r"<sup[^>]*>.*?</sup>", re.IGNORECASE | re.DOTALL)
_SIBOR_PAGENUM_RE = re.compile(
    r"<span class=\"pagenum[^>]*>.*?</span>", re.IGNORECASE | re.DOTALL
)
_SIBOR_LINE_RE = re.compile(r"\((\d{1,4})\)")


def _sibor_book_segment(raw: str, this_anchor: str, next_anchor: str) -> str | None:
    m = re.search(rf'<div id="Book&#95;{this_anchor}"[^>]*>', raw)
    if not m:
        return None
    if next_anchor:
        n = re.search(rf'<div id="Book&#95;{next_anchor}"[^>]*>', raw)
        end = n.start() if n else len(raw)
    else:
        # Book V is the last Jewish book; cut before the editorial references /
        # footnotes block so trailing apparatus is not ingested as text.
        end = raw.find('<div class="references', m.end())
        if end < 0:
            end = raw.find('id="cite_note', m.end())
        if end < 0:
            end = len(raw)
    return raw[m.end():end]


def _sibor_lines(segment: str) -> list[str]:
    seg = _SIBOR_SUP_RE.sub(" ", segment)
    seg = _SIBOR_PAGENUM_RE.sub(" ", seg)
    flat = _clean_text(seg)
    matches = list(_SIBOR_LINE_RE.finditer(flat))
    lines: list[str] = []
    for i, mt in enumerate(matches):
        s = mt.end()
        e = matches[i + 1].start() if i + 1 < len(matches) else len(flat)
        txt = flat[s:e].strip()
        if txt:
            lines.append(txt)
    return lines


def _parse_sibor(work_dir: Path) -> Iterator[HistoricalChunk]:
    candidates = list(work_dir.glob("*.html")) + list(work_dir.glob("*.htm"))
    if not candidates:
        return
    raw = sorted(candidates)[0].read_text(encoding="utf-8", errors="replace")
    for chapter, this_anchor, next_anchor in _SIBOR_BOOKS:
        segment = _sibor_book_segment(raw, this_anchor, next_anchor)
        if segment is None:
            continue
        lines = _sibor_lines(segment)
        # Cluster into strophes; anchor on the running ordinal of the first line
        # in the strophe so every anchor within a book is unique and stable.
        for start in range(0, len(lines), _SIBOR_STROPHE_SIZE):
            strophe = " ".join(lines[start: start + _SIBOR_STROPHE_SIZE])
            if not strophe.strip():
                continue
            verse = start + 1
            yield _make_chunk(
                "sibor", f"{chapter}.{verse}", strophe, contested=_none_contested()
            )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_PARSERS = {
    "1enoch": _parse_enoch,
    "jubilees": _parse_jubilees,
    "test12": _parse_test12,
    "sibor": _parse_sibor,
}


def parse() -> Iterator[HistoricalChunk]:
    """Yield one HistoricalChunk per verse/strophe across the in-scope works.

    Deterministic order: works in SOURCE_SLUGS order, then per-work source
    order (chapter, then verse/strophe). A work whose source directory is
    absent is skipped, so the three works without a clean Charles transcription
    (2baruch, 4ezra, pssol) simply produce no chunks until their data lands.
    """
    for work in SOURCE_SLUGS:
        parser = _PARSERS.get(work)
        if parser is None:
            continue
        work_dir = _ROOT / work
        if not work_dir.is_dir():
            continue
        yield from parser(work_dir)
