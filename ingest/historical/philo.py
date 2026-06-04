"""Philo of Alexandria adapter (C. D. Yonge 1854 English, earlychristianwritings.com).

Pure Pipeline 1 historical adapter. Reads the 45 staged Yonge treatise pages
under ``data/private/historical/philo/bookN.html`` (N = 1..45) and emits one
``HistoricalChunk`` per Cohn-Wendland paragraph in deterministic order.

PURITY: this module performs no network access, no subprocess, no dynamic import.
It reads only literal paths beneath ``data/private/historical/philo/``. The HTML
is fetched by a separate Bash procurement step; the adapter only parses what is
already on disk.

Anchoring follows the scholarly standard: ``philo.<treatise-slug>.<paragraph>``
where ``<treatise-slug>`` is the canonical Latin abbreviation in lowercase kebab
form (with explicit Roman ordinals to avoid the I/II/III collisions) and
``<paragraph>`` is the embedded Cohn-Wendland paragraph integer. The URL
``bookN`` integer is never used as an anchor; it is mapped to a treatise slug
through the frozen 45-row ``BOOK_TO_TREATISE`` table below.

Provenance discipline (docs/HISTORICAL_SCHEMA.md):
  - Books 41-43 (Questions and Answers on Genesis I/II/III) and books 38-39
    (On Providence Fragments I/II) reach Yonge's English only through the chain
    Greek original -> Armenian translation -> Latin translation -> Yonge English.
    These set provenance.witness_chain to the four-step chain and loss_status
    "fragmentary". Hypothetica (book 37) and the Providence fragments survive
    only as quotations in Eusebius; they are marked fragmentary too. The downstream
    Pipeline 4 output carries the "armenian-via-latin" flag for the QG/Providence
    witnesses; the chunk itself has no flags field, so the signal lives in
    provenance.witness_chain and loss_status here.

Editorial overlay discipline (docs/HISTORICAL_SCHEMA.md):
  - Yonge's inline editorial footnote markers "{*}" and "{**...}" and the inline
    scripture-reference braces "{#...}" are stripped from the chunk text and are
    NOT inlined. They are editorial apparatus, not Philo's prose.

Encoding: pages declare iso-8859-1. The prose is ASCII apart from a handful of
mojibake bytes that stand in for an em-dash between clauses (0xF9) and a macron
diacritic on transliterated Greek vowels (0xF7). The dash artifact is rendered as
a comma plus space (the standing dash-discipline rule forbids em and en dashes in
all output), and the macron byte is dropped, leaving readable transliteration.
The trailing per-page JavaScript Greek-font conversion block is stripped before
parsing.
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

SOURCE_SLUGS: tuple[str, ...] = ("philo",)

# Adapter-pure data root: only literal paths under data/private/historical/philo/.
_PHILO_DIR = HISTORICAL_DATA_ROOT / "philo"

_AUTHOR = "Philo of Alexandria"
_DATE_RANGE = "c. 20 BCE - 50 CE"
_LANGUAGE = "en"
_TRANSLATOR = "C. D. Yonge (1854)"
_EDITION = "earlychristianwritings.com Yonge"
_LICENSE = "PD"
_REDISTRIBUTE = True
_ORIGINAL_LANGUAGE = "el"  # Philo wrote in Koine Greek.

# Standard transmission chain for treatises preserved in Greek and rendered into
# English by Yonge.
_CHAIN_GREEK = ("greek-original", "english-yonge-1854")
# QG (books 41-43) and De Providentia (books 38-39) survive only through Armenian
# via Latin. The Yonge English is downstream of that.
_CHAIN_ARMENIAN = (
    "greek-original",
    "armenian-translation",
    "latin-translation",
    "english-yonge-1854",
)

# Book numbers whose text reaches English only through the Armenian-via-Latin
# chain and survives fragmentarily.
_ARMENIAN_BOOKS = frozenset({38, 39, 41, 42, 43})
# Hypothetica (37) and the Providence fragments (38, 39) survive only as
# quotations in Eusebius and are text-critically fragmentary.
_FRAGMENTARY_BOOKS = frozenset({37, 38, 39, 41, 42, 43, 44, 45})

# Books whose paragraph markers carry a compound "(prefix.paragraph)" citation
# and so split the page into several treatise slugs. The value maps the dotted
# prefix integer to the slug suffix appended to the book's base slug. De Somniis
# splits its two ancient books into roman-ordinal slugs (the explicit ordinal is
# required). Hypothetica keeps the Eusebian chapter number as the suffix.
_DOTTED_BOOKS: dict[int, dict[int, str]] = {
    21: {1: "-i", 2: "-ii"},  # de-somniis book I / book II
}
# Hypothetica's dotted prefix is a chapter number; the suffix is "-<chapter>"
# derived at parse time rather than enumerated, so it lives as a flag here.
_HYPOTHETICA_BOOK = 37


# ---------------------------------------------------------------------------
# Frozen 45-row book-number -> (treatise-slug, full English treatise title) table
# ---------------------------------------------------------------------------
# Slugs are the canonical Latin abbreviation in lowercase kebab, with explicit
# Roman ordinals where a base name repeats (Legum Allegoriae I/II/III, De Vita
# Mosis I/II, De Specialibus Legibus I/II/III/IV, QG I/II/III, De Providentia
# I/II). The titles are Yonge's full English titles as listed on the
# earlychristianwritings.com Yonge index. The slug column must match
# ANCHOR_PATTERNS["philo"] = ^philo\.[a-z0-9-]+\.\d+$ (lowercase kebab).
BOOK_TO_TREATISE: dict[int, tuple[str, str]] = {
    1: ("de-opificio", "On the Creation"),
    2: ("legum-allegoriae-i", "Allegorical Interpretation, I"),
    3: ("legum-allegoriae-ii", "Allegorical Interpretation, II"),
    4: ("legum-allegoriae-iii", "Allegorical Interpretation, III"),
    5: ("de-cherubim", "On the Cherubim"),
    6: (
        "de-sacrificiis",
        "On the Birth of Abel and the Sacrifices Offered by Him and by His "
        "Brother Cain",
    ),
    7: ("quod-deterius", "That the Worse is Wont to Attack the Better"),
    8: ("de-posteritate", "On the Posterity of Cain and His Exile"),
    9: ("de-gigantibus", "On the Giants"),
    10: ("quod-deus", "On the Unchangableness of God"),
    11: ("de-agricultura", "On Husbandry"),
    12: ("de-plantatione", "Concerning Noah's Work as a Planter"),
    13: ("de-ebrietate", "On Drunkenness"),
    14: (
        "de-sobrietate",
        "On the Prayers and Curses Uttered by Noah When He Became Sober",
    ),
    15: ("de-confusione", "On the Confusion of Tongues"),
    16: ("de-migratione", "On the Migration of Abraham"),
    17: ("quis-heres", "Who is the Heir of Divine Things?"),
    18: ("de-congressu", "On Mating with the Preliminary Studies"),
    19: ("de-fuga", "On Flight and Finding"),
    20: ("de-mutatione", "On the Change of Names"),
    21: ("de-somniis", "On Dreams, That They are God-Sent"),
    22: ("de-abrahamo", "On Abraham"),
    23: ("de-iosepho", "On Joseph"),
    24: ("de-vita-mosis-i", "On the Life of Moses, I"),
    25: ("de-vita-mosis-ii", "On the Life of Moses, II"),
    26: ("de-decalogo", "The Decalogue"),
    27: ("de-specialibus-legibus-i", "The Special Laws, I"),
    28: ("de-specialibus-legibus-ii", "The Special Laws, II"),
    29: ("de-specialibus-legibus-iii", "The Special Laws, III"),
    30: ("de-specialibus-legibus-iv", "The Special Laws, IV"),
    31: ("de-virtutibus", "On the Virtues"),
    32: ("de-praemiis", "On Rewards and Punishments"),
    33: ("quod-omnis-probus", "Every Good Man is Free"),
    34: ("de-vita-contemplativa", "On the Contemplative Life or Suppliants"),
    35: ("de-aeternitate", "On the Eternity of the World"),
    36: ("in-flaccum", "Flaccus"),
    37: ("hypothetica", "Hypothetica: Apology for the Jews"),
    38: ("de-providentia-i", "On Providence: Fragment I"),
    39: ("de-providentia-ii", "On Providence: Fragment II"),
    40: (
        "legatio-ad-gaium",
        "On the Embassy to Gaius: The First Part of the Treatise on Virtues",
    ),
    41: ("qg-i", "Questions and Answers on Genesis, I"),
    42: ("qg-ii", "Questions and Answers on Genesis, II"),
    43: ("qg-iii", "Questions and Answers on Genesis, III"),
    44: ("appendix-de-mundo", "Appendix 1: Concerning the World"),
    45: ("appendix-fragmenta", "Appendix 2: Fragments"),
}

# Anchor-pattern guard mirrored from pipeline4.historical_schema so a future
# typo in BOOK_TO_TREATISE is caught at import time, not at validation time.
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
for _n, (_slug, _title) in BOOK_TO_TREATISE.items():
    if not _SLUG_RE.match(_slug):
        raise ValueError(f"BOOK_TO_TREATISE slug for book {_n} is not lowercase kebab")
if len(BOOK_TO_TREATISE) != 45:
    raise ValueError("BOOK_TO_TREATISE must have exactly 45 rows")
if len({s for s, _ in BOOK_TO_TREATISE.values()}) != 45:
    raise ValueError("BOOK_TO_TREATISE slugs must be unique")


# ---------------------------------------------------------------------------
# Parsing primitives (pure string transforms)
# ---------------------------------------------------------------------------

# A Cohn-Wendland paragraph marker: "(N)" possibly with stray internal spaces
# (the source has a "( 292)" typo). It is NOT immediately followed by "{": that
# form ("Word(N){#ref}") is an inline scripture-reference marker, not a
# paragraph, so the negative lookahead excludes it.
_PARA_RE = re.compile(r"\(\s*(\d+)\s*\)(?!\{)")
# Two treatises cite by a compound "(book.paragraph)" or "(chapter.section)"
# marker rather than a flat "(N)": De Somniis (book 21, two ancient books bundled
# under one URL) uses "(1.1)" / "(2.5)" with the prefix being the ancient book
# number, and Hypothetica (book 37, preserved fragmentarily via Eusebius) uses
# "(5.11)" / "(6.1)" with the prefix being the Eusebian chapter. The dotted
# prefix is folded into the treatise slug so the final anchor segment stays a
# bare integer (^philo\.[a-z0-9-]+\.\d+$): De Somniis -> de-somniis-i/-ii,
# Hypothetica -> hypothetica-<chapter>.
_DOTTED_RE = re.compile(r"\(\s*(\d+)\.(\d+)\s*\)(?!\{)")
_SCRIPT_RE = re.compile(r"(?is)<script.*?</script>")
_STYLE_RE = re.compile(r"(?is)<style.*?</style>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Editorial apparatus stripped from prose. Every brace-delimited span in the
# Yonge text is editorial: the "{*}" / "{**...}" title footnotes, the "{#ref}"
# inline scripture citations, the numeric "{12}" footnote-reference markers, and
# Yonge's bracketed translator notes ("{Genesis 39:1.}", "{there is an hiatus
# here}"). All are removed; none are inlined. The "(#ref)" parenthesized
# scripture citations (used in the Armenian-via-Latin QG treatises) are the same
# editorial apparatus in a different wrapper and are stripped too.
_FN_DOUBLE_RE = re.compile(r"(?s)\{\*\*.*?\}")  # {**Yonge's title, ...}
_FN_SINGLE_RE = re.compile(r"\{\*\}")  # {*}
_FN_BRACE_RE = re.compile(r"(?s)\{[^{}]*\}")  # any {...} editorial note
_FN_PAREN_REF_RE = re.compile(r"\(#[^)]*\)")  # (#Ge 2:4) scripture citation
# A standalone trailing Roman-numeral chapter marker bleeding into a paragraph
# tail (Yonge's editorial chapter heads, e.g. " VII." before the next paragraph).
_TRAILING_ROMAN_RE = re.compile(r"\s+[IVXLCDM]+\.\s*$")
# A space left before sentence punctuation when an inline citation was removed
# (e.g. 'created?" (#Ge 2:4).' -> 'created?" .' -> 'created?".').
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")

# Prose-end sentinel: every Yonge page closes the treatise with a centred
# "Go to the Tables of Contents" line before the footer chrome.
_END_SENTINELS = ("Go to the", "Tables of Contents")


def _clean_decode(raw: bytes) -> str:
    """Decode iso-8859-1 and drop the script/style blocks (incl. the tail JS)."""
    txt = raw.decode("iso-8859-1")
    txt = _SCRIPT_RE.sub(" ", txt)
    txt = _STYLE_RE.sub(" ", txt)
    return txt


def _strip_editorial(text: str) -> str:
    """Pre-split removal of the title footnote block (it precedes paragraph 1).

    Only the "{**...}" / "{*}" title-region markers are removed here, before the
    page is sliced on paragraph markers. The remaining brace notes and scripture
    citations are stripped per paragraph in ``_normalize`` so that stripping never
    disturbs the offsets used to delimit one paragraph from the next.
    """
    text = _FN_DOUBLE_RE.sub(" ", text)
    text = _FN_SINGLE_RE.sub(" ", text)
    return text


def _normalize(text: str) -> str:
    """Strip editorial apparatus and tags, unescape, repair mojibake, NFC.

    Brace notes and "(#ref)" scripture citations are removed first so the
    paragraph text carries no editorial overlay; then HTML tags are dropped and
    entities unescaped.
    """
    text = _FN_BRACE_RE.sub(" ", text)
    text = _FN_PAREN_REF_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    # Mojibake repair: 0xF9 stands in for a clause em-dash (banned glyph), 0xF7
    # for a macron diacritic over transliterated Greek vowels. Yonge's double
    # hyphen "--" also functions as a dash. Render dashes as a comma plus space;
    # drop the macron byte.
    text = text.replace("ù", ", ")
    text = text.replace("÷", "")
    text = text.replace("--", ", ")
    text = _WS_RE.sub(" ", text).strip()
    # Tidy whitespace left where an inline citation was stripped: a space before
    # closing punctuation, and a doubled punctuation mark.
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _TRAILING_ROMAN_RE.sub("", text).strip()
    return unicodedata.normalize("NFC", text)


def _body(txt: str) -> str:
    """Trim the decoded page to the prose body (drop the closing nav and footer)."""
    end = -1
    for sentinel in _END_SENTINELS:
        idx = txt.find(sentinel)
        if idx != -1:
            end = idx
            break
    return txt if end == -1 else txt[:end]


def _prose_region(txt: str) -> str:
    """Slice from the first flat "(1)" marker to the closing nav sentinel."""
    body = _body(txt)
    first = re.search(r"\(\s*1\s*\)(?!\{)", body)
    if first is None:
        return ""
    return _strip_editorial(body[first.start() :])


def _iter_paragraphs(raw: bytes) -> Iterator[tuple[str, int, str]]:
    """Yield (slug_suffix, paragraph_number, text) for flat "(N)" treatises.

    A marker is accepted only when its integer equals the next expected number.
    This rejects out-of-sequence inline references (scripture cross-references and
    the like) while tolerating the "( 292)" internal-space typo, and guarantees a
    strictly increasing, gap-free anchor sequence per treatise. The slug suffix is
    always empty for flat treatises.
    """
    txt = _clean_decode(raw)
    region = _prose_region(txt)
    if not region:
        return
    accepted: list[tuple[int, int]] = []  # (num, end-of-marker)
    starts: list[int] = []
    nxt = 1
    for m in _PARA_RE.finditer(region):
        num = int(m.group(1))
        if num == nxt:
            accepted.append((num, m.end()))
            starts.append(m.start())
            nxt += 1
    for i, (num, marker_end) in enumerate(accepted):
        text_end = starts[i + 1] if i + 1 < len(starts) else len(region)
        text = _normalize(region[marker_end:text_end])
        if text:
            yield ("", num, text)


def _iter_dotted(raw: bytes, book: int) -> Iterator[tuple[str, int, str]]:
    """Yield (slug_suffix, paragraph_number, text) for "(prefix.paragraph)" pages.

    De Somniis (book 21) and Hypothetica (book 37) cite by a compound marker. The
    dotted prefix becomes a slug suffix so the final anchor segment stays a bare
    integer: De Somniis -> -i/-ii (the ancient book), Hypothetica -> -<chapter>
    (the Eusebian chapter). Markers are taken in document order; a per-prefix
    monotonic guard rejects out-of-order inline references within each section.
    """
    txt = _clean_decode(raw)
    region = _strip_editorial(_body(txt))
    matches = list(_DOTTED_RE.finditer(region))
    if not matches:
        return
    suffix_map = _DOTTED_BOOKS.get(book)
    # Per-prefix expected-next guard for monotonic acceptance within a section.
    expected: dict[int, int] = {}
    accepted: list[tuple[int, int, int, int]] = []  # (prefix, para, start, end)
    for m in matches:
        prefix = int(m.group(1))
        para = int(m.group(2))
        nxt = expected.get(prefix, 1)
        if para == nxt:
            accepted.append((prefix, para, m.start(), m.end()))
            expected[prefix] = nxt + 1
    for i, (prefix, para, _start, marker_end) in enumerate(accepted):
        text_end = accepted[i + 1][2] if i + 1 < len(accepted) else len(region)
        text = _normalize(region[marker_end:text_end])
        if not text:
            continue
        # De Somniis maps the prefix through suffix_map; Hypothetica keeps the
        # chapter number as the suffix.
        suffix = suffix_map.get(prefix, f"-{prefix}") if suffix_map else f"-{prefix}"
        yield (suffix, para, text)


def _fragment_paragraphs(raw: bytes) -> Iterator[tuple[str, int, str]]:
    """Fallback for appendix and Eusebian-excerpt pages with no (N) numbering.

    Books 44 and 45 (the two appendices) organize their text by John-of-Damascus
    page references, and book 38 (Providence Fragment I) is a continuous Eusebius
    excerpt; none carry Cohn-Wendland paragraph numbers. Split the prose region
    into block paragraphs (the "<p>" structure) and number them sequentially from
    1 so the anchor still satisfies ^philo\\.[a-z0-9-]+\\.\\d+$. Suffix is empty.
    """
    txt = _clean_decode(raw)
    region = _strip_editorial(_body(txt))
    # Split on paragraph break tags; the raw region still holds <p> markers.
    blocks = re.split(r"(?i)<p\b[^>]*>", region)
    n = 0
    for block in blocks:
        text = _normalize(block)
        # Skip short structural fragments (page labels, section headings, single
        # Roman numerals) and the site-chrome breadcrumb block that opens each
        # page ("Philo: ... Home > The Works of Philo > Book N").
        if len(text) < 40:
            continue
        if "The Works of Philo" in text or "Tables of Contents" in text:
            continue
        n += 1
        yield ("", n, text)


def _make_chunk(
    book: int, slug: str, suffix: str, title: str, para: int, text: str
) -> HistoricalChunk:
    full_slug = f"{slug}{suffix}"
    anchor = f"philo.{full_slug}.{para}"
    chain = list(_CHAIN_ARMENIAN if book in _ARMENIAN_BOOKS else _CHAIN_GREEK)
    loss = "fragmentary" if book in _FRAGMENTARY_BOOKS else "complete"
    return HistoricalChunk(
        chunk_id=anchor,
        source_type="jewish-philosopher",
        source=WitnessSource(
            source_slug="philo",
            work_id=f"philo.{full_slug}",
            work_title=title,
            author=_AUTHOR,
            date_written_range=_DATE_RANGE,
            anchor_id=anchor,
            anchor_alt_citation=None,
            language=_LANGUAGE,
            translator=_TRANSLATOR,
            edition=_EDITION,
        ),
        contested_interpolation=ContestedInterpolation(
            type="none", note=None, redact_for_embedding=False
        ),
        provenance=Provenance(
            original_language=_ORIGINAL_LANGUAGE,
            witness_chain=chain,
            extant_witnesses=[],
            loss_status=loss,
        ),
        text=text,
        text_to_embed=text,
        license=_LICENSE,
        redistribute=_REDISTRIBUTE,
        license_note=None,
    )


def parse_book(raw: bytes, book: int) -> list[HistoricalChunk]:
    """Parse one Yonge page (bytes) for the given book number into chunks.

    Pure transform over the raw HTML bytes; the file read is the caller's job.
    This is the testable seam exercised by the fixture tests. Selects the flat,
    compound, or block-fallback paragraph strategy per the book's structure.
    """
    if book not in BOOK_TO_TREATISE:
        raise ValueError(f"book number {book} is out of the 1..45 range")
    slug, title = BOOK_TO_TREATISE[book]
    if book in _DOTTED_BOOKS or book == _HYPOTHETICA_BOOK:
        # Compound "(prefix.paragraph)" treatises (De Somniis, Hypothetica).
        paras = list(_iter_dotted(raw, book))
    else:
        paras = list(_iter_paragraphs(raw))
    if not paras:
        # Appendix pages and continuous Eusebian excerpts with no Cohn-Wendland
        # numbering use the block fallback so their prose is not silently dropped.
        paras = list(_fragment_paragraphs(raw))
    return [
        _make_chunk(book, slug, suffix, title, para_num, text)
        for suffix, para_num, text in paras
    ]


def parse() -> Iterator[HistoricalChunk]:
    """Parse the 45 staged Yonge pages into HistoricalChunk records.

    Deterministic order: book 1..45, then paragraph 1..N within each book. Pages
    that are absent from disk are skipped (the loader reports the shortfall); the
    adapter never fabricates content. Pure: reads only data/private files.
    """
    for book in range(1, 46):
        path: Path = _PHILO_DIR / f"book{book}.html"
        if not path.exists():
            continue
        yield from parse_book(path.read_bytes(), book)
