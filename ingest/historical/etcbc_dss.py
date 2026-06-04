"""Dead Sea Scrolls (ETCBC/dss Text-Fabric) historical ingest adapter.

Parses the ETCBC/dss Text-Fabric dataset (Martin Abegg's transcriptions,
converted to Text-Fabric by Jacobs, Naaijer and Roorda) into one
HistoricalChunk per scroll line. The dataset is the only clean machine-readable
DSS corpus available; see the DSS-ETCBC entry in
docs/historical_data_inventory_catalog.json.

OPTION A DISCIPLINE (locked, docs/HISTORICAL_SCHEMA.md "DSS (Option A)"):
``text`` and ``text_to_embed`` both carry the ETCBC transliteration verbatim
from the ``fulle`` feature, preserving every bracket and flag the dataset
records ([ ] reconstruction, ( ) alternate, # uncertain trace, ? uncertain
letter, 0 vacat, etc.). No engine-authored English gloss is pre-baked; English
meaning is rendered at Pipeline 3 synthesis time.

LICENSE: CC-BY-NC-4.0 (verbatim "@license=Creative Commons
Attribution-NonCommercial 4.0 International License" in every .tf header).
``redistribute`` is False at the chunk level; the license guard blocks bulk
export. Local storage and personal query are permitted by the NC clause.

Text-Fabric data model (verified against tf/2.0/):

  otype.tf node ranges:
    sign  1-1430241          (the base slot type)
    fragment 1531341-1542522
    line     1552973-1605867
    scroll   1605868-1606868
    word     1606869-2107863

  Section hierarchy (otext.tf @sectionFeatures): scroll, fragment, line.
  The features scroll/fragment/line/biblical are defined on LINE nodes.
  The transliteration feature ``fulle`` and the spacing feature ``after`` and
  the language feature ``lang_etcbc`` are defined on WORD nodes.
  ``oslots.tf`` maps every non-slot node to its sign slots; a line's signs form
  a contiguous range, so words are assigned to a line by sign containment.

Anchor convention (docs/HISTORICAL_SCHEMA.md, DSS_ANCHOR_RE):
  Columnar scrolls (1QS, 1QM, 11Q19, ...) record the column in the ``fragment``
  feature as a bare integer -> ``<slug>.col<NN>.line<NN>``.
  Fragmentary scrolls (4Q...) record an ``f``-prefixed label (``f7ii``,
  ``f1_2i``) -> ``<slug>.f<frag>.line<NN>``. Separator characters in the source
  label (``_``, ``+``, spaces) are dropped so the anchor matches
  ``f[0-9a-z]+``; the original label is preserved in ``anchor_alt_citation``.

Coverage caveat (honest, see module docstring tail and the parse() report):
The schema's QUMRAN_SLUG_RE (``^\\d{1,2}Q[a-z0-9-]+$``) and DSS_ANCHOR_RE
(``^\\d{1,2}q...``) permit ONE OR TWO leading digits before the ``Q`` (caves 1
through 11) and require a ``q`` in the slug. The full Qumran corpus is therefore
emitted: single-digit-cave sigla (1Q..., 4Q..., ...) AND two-digit-cave sigla
(11Q19 Temple Scroll, 11Q5 = 11QPsa, 10Q1, ...) all produce schema-valid
anchors. The corpus is kept in full; balancing against other historical sources
is a retrieval-time concern, not an ingest-time trim.

Only sigla that cannot form a valid DSS anchor AT ALL are skipped: those that
lack a ``q`` (CD = Cairo Damascus, Mas*, Mur*, PAM*) or carry a slash
(5/6Hev*). The named-but-unrepresentable ``cd`` slug is among them: ``cd`` is an
allowed source_slug yet ``cd.col01.line01`` fails DSS_ANCHOR_RE because the
regex needs a ``q``. The adapter never fudges an anchor to force validation; it
skips and the run reports the skipped counts.

PURITY: reads only plain-text ``.tf`` files under
HISTORICAL_DATA_ROOT / "dss" / "repo" / "tf" / <version>. No network, no
subprocess, no dynamic import, and crucially NO use of the ``text-fabric``
runtime library (which reads private/non-data paths). The .tf files are parsed
directly as the line-oriented text format they are. Cloning the ETCBC/dss repo
into data/private is a separate procurement step performed outside this module.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from ingest.historical._common import HISTORICAL_DATA_ROOT
from pipeline4.historical_schema import (
    DSS_ANCHOR_RE,
    NAMED_SOURCE_SLUGS,
    QUMRAN_SLUG_RE,
    ContestedInterpolation,
    HistoricalChunk,
    Provenance,
    WitnessSource,
)

# Representative tuple of scroll slugs this adapter emits (the schema-named DSS
# scrolls; the live corpus emits hundreds more, across caves 1 through 11).
SOURCE_SLUGS: tuple[str, ...] = (
    "1qs",
    "1qsa",
    "1qsb",
    "1qm",
    "1qha",
    "1qphab",
    "11q19",
    "1qisaa",
)

_DSS_ROOT = HISTORICAL_DATA_ROOT / "dss" / "repo" / "tf"

# The base slot type and the required section/feature node types.
_SLOT_TYPE = "sign"
_LINE_TYPE = "line"
_WORD_TYPE = "word"

_DEFAULT_VERSION = "2.0"

# Human-readable titles for the marquee scrolls (docs/HISTORICAL_SCHEMA.md).
# Scrolls absent from this map fall back to their siglum as the title.
_SCROLL_TITLES: dict[str, str] = {
    "1qs": "Community Rule",
    "1qsa": "Rule of the Congregation",
    "1qsb": "Rule of Blessings",
    "1qm": "War Scroll",
    "1qha": "Hodayot (Thanksgiving Hymns)",
    "1qphab": "Pesher Habakkuk",
    "11q19": "Temple Scroll",
    "1qisaa": "Great Isaiah Scroll",
    "4q394": "4QMMT (Some Works of the Torah)",
    "4q395": "4QMMT (Some Works of the Torah)",
    "4q396": "4QMMT (Some Works of the Torah)",
    "4q397": "4QMMT (Some Works of the Torah)",
    "4q398": "4QMMT (Some Works of the Torah)",
    "4q399": "4QMMT (Some Works of the Torah)",
    "4q174": "Florilegium",
    "4q521": "Messianic Apocalypse",
}

# Composition-date best-estimates. The Qumran corpus as a whole is copied
# c. 250 BCE to 68 CE; per-scroll palaeographic dates are used where the scroll
# is a marquee witness, otherwise the corpus-wide range is given.
_SCROLL_DATES: dict[str, str] = {
    "1qs": "c. 100 BCE",
    "1qsa": "c. 100 BCE",
    "1qsb": "c. 100 BCE",
    "1qm": "c. 50 BCE to 25 CE",
    "1qha": "c. 50 BCE",
    "1qphab": "c. 50 BCE to 25 CE",
    "11q19": "c. 50 BCE to 25 CE",
    "1qisaa": "c. 125 BCE",
    "4q394": "c. 75 BCE to 50 CE",
    "4q395": "c. 75 BCE to 50 CE",
    "4q396": "c. 75 BCE to 50 CE",
    "4q397": "c. 75 BCE to 50 CE",
    "4q398": "c. 75 BCE to 50 CE",
    "4q399": "c. 75 BCE to 50 CE",
}
_CORPUS_DATE = "c. 250 BCE to 68 CE"

_LICENSE = "CC-BY-NC-4.0"
_LICENSE_NOTE = (
    "ETCBC/dss Text-Fabric transliteration under CC-BY-NC-4.0; "
    "non-commercial local storage and personal query only, not redistributable."
)
_EDITION = "ETCBC/dss Text-Fabric (fulle feature, tf/{version})"

# Separator characters that appear in ETCBC fragment labels, each mapped to a
# distinct lowercase letter so the sanitized anchor stays injective (otherwise
# 'f1_5' and 'f15' would both collapse to 'f15' and collide). The full set of
# non-alphanumeric characters present in the fragment feature is
# {'(', ')', '+', '?', '_', '|'}; any future addition trips the dedup guard in
# parse() and fails loudly rather than silently colliding.
_FRAG_SEP_MAP = {
    "_": "u",  # underscore (fragment range, e.g. f1_5 = fragments 1 to 5)
    "+": "p",  # plus (joined fragments, e.g. f2i+3)
    "(": "o",
    ")": "c",
    "|": "b",
    "?": "q",
}
_NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Z]")


# ---------------------------------------------------------------------------
# Text-Fabric .tf plain-text parsing (no text-fabric library at runtime)
# ---------------------------------------------------------------------------


def _data_lines(path: Path) -> Iterator[str]:
    """Yield the data lines of a .tf file (everything after the @-header block).

    A .tf file is a metadata header (lines beginning with @) then one blank line
    then the node-aligned data. We treat any line that does not start with @ and
    is not the single header-terminating blank as data; a robust reader simply
    skips @-lines and empty lines, which is what every feature here needs.
    """
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            if raw.startswith("@"):
                continue
            line = raw.rstrip("\n")
            if line == "":
                continue
            yield line


def _load_node_feature(path: Path) -> dict[int, str]:
    """Load a node feature .tf file into ``{node: value}``.

    Text-Fabric sparse encoding: a data line is either ``<node>\\t<value>`` (or
    ``<lo>-<hi>\\t<value>`` for a node range) which sets the current node, or a
    bare ``<value>`` which applies to the previous node + 1. A line that
    contains a tab but whose left side is not a node number (e.g. a value that
    itself begins with whitespace then a tab) is treated as a bare value.
    """
    out: dict[int, str] = {}
    cur = 0
    for line in _data_lines(path):
        if "\t" in line:
            spec, value = line.split("\t", 1)
            if spec and spec[0].isdigit():
                if "-" in spec:
                    lo_s, hi_s = spec.split("-", 1)
                    lo, hi = int(lo_s), int(hi_s)
                    for node in range(lo, hi + 1):
                        out[node] = value
                    cur = hi
                else:
                    cur = int(spec)
                    out[cur] = value
                continue
        # Bare value line.
        cur += 1
        out[cur] = line
    return out


def _load_oslots(path: Path, max_slot: int) -> dict[int, tuple[int, int]]:
    """Load oslots.tf into ``{node: (first_sign, last_sign)}``.

    oslots is an edge feature: each non-slot node lists its slot signs as a
    comma-separated list of ints and ``lo-hi`` ranges. Only the span endpoints
    are needed to assign words to lines by containment, so we keep
    ``(min_sign, max_sign)`` per node rather than the full slot set.

    ``max_slot`` is the highest slot (sign) node; the first non-slot node that a
    bare leading line refers to is ``max_slot + 1``.
    """
    out: dict[int, tuple[int, int]] = {}
    # Non-slot nodes start at the first node above the sign range.
    cur = max_slot
    for line in _data_lines(path):
        if "\t" in line:
            spec, value = line.split("\t", 1)
            cur = int(spec)
        else:
            cur += 1
            value = line
        first: int | None = None
        last: int | None = None
        for part in value.split(","):
            if "-" in part:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
            else:
                lo = hi = int(part)
            if first is None or lo < first:
                first = lo
            if last is None or hi > last:
                last = hi
        if first is not None and last is not None:
            out[cur] = (first, last)
    return out


def _load_otype_ranges(version_dir: Path) -> dict[str, tuple[int, int]]:
    """Read otype.tf into ``{otype: (lo, hi)}`` for this TF version or fixture.

    otype.tf lists each node type as ``<lo>-<hi>\\t<otype>`` (a single-node type
    would be ``<n>\\t<otype>``). Ranges are read directly so the parser slices
    correctly regardless of TF version or a trimmed test fixture, rather than
    trusting a pinned constant. The slot/line/word types are required.
    """
    ranges: dict[str, tuple[int, int]] = {}
    for line in _data_lines(version_dir / "otype.tf"):
        if "\t" not in line:
            continue
        spec, otype = line.split("\t", 1)
        if "-" in spec:
            lo_s, hi_s = spec.split("-", 1)
            ranges[otype] = (int(lo_s), int(hi_s))
        elif spec.isdigit():
            n = int(spec)
            ranges[otype] = (n, n)
    for required in (_SLOT_TYPE, _LINE_TYPE, _WORD_TYPE):
        if required not in ranges:
            raise ValueError(
                f"otype.tf at {version_dir} is missing the {required!r} node "
                f"type; cannot parse."
            )
    return ranges


# ---------------------------------------------------------------------------
# Anchor / slug helpers
# ---------------------------------------------------------------------------


def _slugify(scroll_name: str) -> str:
    return scroll_name.lower()


def _slug_is_valid(slug: str) -> bool:
    return slug in NAMED_SOURCE_SLUGS or bool(QUMRAN_SLUG_RE.match(slug))


def _build_anchor(slug: str, fragment: str, line_label: str) -> str | None:
    """Build a DSS anchor, or None if the source labels cannot form a valid one.

    Columnar (fragment is a bare integer) -> ``<slug>.col<NN>.line<NN>``.
    Fragmentary (anything else)            -> ``<slug>.f<frag>.line<NN>``.
    Returns None when the line label is non-numeric (a few lines carry labels
    like 'a' or '?'); such lines are skipped rather than coerced.
    """
    if not line_label.isdigit():
        return None
    line_part = f"line{int(line_label):02d}"

    if fragment.isdigit():
        frag_part = f"col{int(fragment):02d}"
    else:
        body = fragment
        if body[:1] in ("f", "F"):
            body = body[1:]
        # Case is preserved in the fragment label: the ETCBC dataset uses case to
        # distinguish fragments (4Q585 has both 'fA' and 'fa'); lowercasing would
        # collapse them. DSS_ANCHOR_RE is case-insensitive, so an uppercase letter
        # in the fragment body still matches f[0-9a-z]+. Map known separators to
        # distinct letters, then drop anything still outside the alphanumerics.
        body = "".join(_FRAG_SEP_MAP.get(ch, ch) for ch in body)
        body = _NON_ALNUM_RE.sub("", body)
        if not body:
            return None
        frag_part = f"f{body}"

    anchor = f"{slug}.{frag_part}.{line_part}"
    if not DSS_ANCHOR_RE.match(anchor):
        return None
    return anchor


def _line_language(langs: list[str]) -> str:
    """Map the majority ETCBC word-language of a line to an ISO 639-3 code."""
    if not langs:
        return "hbo"
    counts: dict[str, int] = defaultdict(int)
    for value in langs:
        counts[value] += 1
    top = max(counts, key=lambda k: (counts[k], k))
    return {"Aramaic": "arc", "Greek": "grc"}.get(top, "hbo")


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------


def _resolve_version_dir() -> Path:
    """Pick the TF version directory: prefer the pinned default, else the latest."""
    default = _DSS_ROOT / _DEFAULT_VERSION
    if (default / "otype.tf").exists():
        return default
    if not _DSS_ROOT.exists():
        raise FileNotFoundError(
            f"ETCBC/dss Text-Fabric tree not found at {_DSS_ROOT}. Clone with: "
            f"git clone --depth 1 https://github.com/ETCBC/dss "
            f"data/private/historical/dss/repo"
        )
    candidates = sorted(
        (p for p in _DSS_ROOT.iterdir() if (p / "otype.tf").exists()),
        key=lambda p: p.name,
    )
    if not candidates:
        raise FileNotFoundError(f"no TF version with otype.tf under {_DSS_ROOT}")
    return candidates[-1]


def parse() -> Iterator[HistoricalChunk]:
    """Yield one HistoricalChunk per schema-valid scroll line, in node order.

    Resolves the cloned ETCBC/dss Text-Fabric tree under data/private and
    delegates to ``_parse_tf_dir``. Deterministic: see ``_parse_tf_dir``.
    """
    yield from _parse_tf_dir(_resolve_version_dir())


def _parse_tf_dir(version_dir: Path) -> Iterator[HistoricalChunk]:
    """Parse one Text-Fabric version directory into HistoricalChunk records.

    Pure and offline: reads only the plain-text ``.tf`` files in
    ``version_dir``. The same code path serves the full cloned corpus and the
    trimmed test fixtures, so the tests exercise the real parser.

    Deterministic: line nodes are visited in ascending node order, which is the
    canonical scroll -> fragment/column -> line order of the dataset, so two
    runs produce byte-identical output.
    """
    version = version_dir.name
    otype = _load_otype_ranges(version_dir)

    scroll_feat = _load_node_feature(version_dir / "scroll.tf")
    fragment_feat = _load_node_feature(version_dir / "fragment.tf")
    line_feat = _load_node_feature(version_dir / "line.tf")
    biblical_feat = _load_node_feature(version_dir / "biblical.tf")
    fulle_feat = _load_node_feature(version_dir / "fulle.tf")
    after_feat = _load_node_feature(version_dir / "after.tf")
    lang_feat = _load_node_feature(version_dir / "lang_etcbc.tf")
    oslots = _load_oslots(version_dir / "oslots.tf", otype[_SLOT_TYPE][1])

    line_lo, line_hi = otype[_LINE_TYPE]
    word_lo, word_hi = otype[_WORD_TYPE]

    # Index lines by their sign span so words can be assigned by containment.
    line_spans: list[tuple[int, int, int]] = []  # (first_sign, last_sign, node)
    for node in range(line_lo, line_hi + 1):
        span = oslots.get(node)
        if span is not None:
            line_spans.append((span[0], span[1], node))
    line_spans.sort()
    span_starts = [s[0] for s in line_spans]

    def line_of_sign(sign: int) -> int | None:
        idx = bisect_right(span_starts, sign) - 1
        if idx >= 0:
            first, last, node = line_spans[idx]
            if first <= sign <= last:
                return node
        return None

    # Assign words to lines (words ordered ascending so per-line word order is
    # the natural reading order of the line).
    words_by_line: dict[int, list[int]] = defaultdict(list)
    for word in range(word_lo, word_hi + 1):
        span = oslots.get(word)
        if span is None:
            continue
        node = line_of_sign(span[0])
        if node is not None:
            words_by_line[node].append(word)

    edition = _EDITION.format(version=version)
    seen_chunk_ids: set[str] = set()

    for node in range(line_lo, line_hi + 1):
        scroll_name = scroll_feat.get(node)
        if scroll_name is None:
            continue
        slug = _slugify(scroll_name)
        if not _slug_is_valid(slug):
            continue

        fragment_label = fragment_feat.get(node)
        line_label = line_feat.get(node)
        if fragment_label is None or line_label is None:
            continue

        anchor = _build_anchor(slug, fragment_label, line_label)
        if anchor is None:
            continue

        words = words_by_line.get(node)
        if not words:
            continue

        text = "".join(
            (fulle_feat.get(w, "") or "") + (after_feat.get(w, "") or "")
            for w in words
        )
        text = unicodedata.normalize("NFC", text).strip()
        if not text:
            continue

        biblical_value = biblical_feat.get(node)
        is_biblical = biblical_value in {"1", "2"}
        source_type = "qumran-biblical" if is_biblical else "qumran-sectarian"

        language = _line_language(
            [lang_feat[w] for w in words if w in lang_feat]
        )
        original_language = language

        # Columnar vs fragmentary -> witness_chain cave label and loss_status.
        cave_match = re.match(r"^(\d+)q", slug)
        cave = cave_match.group(1) if cave_match else "?"
        witness_chain = [f"qumran-cave-{cave}", f"etcbc-dss-tf-{version}"]

        # Columnar scrolls are damaged but substantial; fragmentary ones are not.
        loss_status = "partial" if fragment_label.isdigit() else "fragmentary"

        alt_citation = (
            None
            if fragment_label.isdigit()
            else f"{scroll_name} frag {fragment_label} line {line_label}"
        )

        work_title = _SCROLL_TITLES.get(slug, scroll_name)
        date_written = _SCROLL_DATES.get(slug, _CORPUS_DATE)

        source = WitnessSource(
            source_slug=slug,
            work_id=slug,
            work_title=work_title,
            author=None,
            date_written_range=date_written,
            anchor_id=anchor,
            anchor_alt_citation=alt_citation,
            language=language,
            translator=None,
            edition=edition,
        )
        provenance = Provenance(
            original_language=original_language,
            witness_chain=witness_chain,
            extant_witnesses=[scroll_name],
            loss_status=loss_status,
        )

        if anchor in seen_chunk_ids:
            raise ValueError(
                f"duplicate DSS anchor {anchor!r} (scroll {scroll_name!r}, "
                f"fragment {fragment_label!r}, line {line_label!r}); the "
                f"fragment-label sanitization produced a collision. Extend "
                f"_FRAG_SEP_MAP so distinct source labels map to distinct anchors."
            )
        seen_chunk_ids.add(anchor)

        yield HistoricalChunk(
            chunk_id=anchor,
            source_type=source_type,
            source=source,
            contested_interpolation=ContestedInterpolation(type="none"),
            provenance=provenance,
            text=text,
            text_to_embed=text,  # Option A: transliteration verbatim, no gloss.
            license=_LICENSE,
            redistribute=False,
            license_note=_LICENSE_NOTE,
        )
