"""Sefaria Mishnah historical ingest adapter.

Parses the sixty-three tractates of the Mishnah from the Sefaria-Export merged
JSON files into one HistoricalChunk per mishnah paragraph. The canonical text is
the HEBREW Torat Emet 357 edition (Public Domain), consistent with the engine's
original-language lexical posture. voyage-4-large is multilingual, so the Hebrew
surface is used directly for both ``text`` and ``text_to_embed`` (no engine
authored English gloss is pre-baked; Pipeline 3 renders meaning at query time).

Hebrew is chosen over the English merged stream deliberately. Sefaria's English
merged.json for many tractates resolves to the William Davidson Edition, which
is CC-BY-NC and forbidden for a redistributable artefact (see
docs/HISTORICAL_SCHEMA.md "license fields"). Torat Emet 357 is uniformly Public
Domain across all sixty-three tractates (verified during procurement: every
fetched merged.json carries ``versions[0] = ["Torat Emet 357", ...]``), so the
Hebrew path is both the cleanest license and the most faithful textual witness.

Source layout (procured to data/private/historical/mishnah/<tractate-slug>/):

    <tractate-slug>/hebrew_merged.json

Each merged.json is a top-level dict with ``title``, ``language`` ("he"),
``versionTitle`` ("merged"), ``versions`` (list of [versionTitle, versionSource]
pairs, Torat Emet 357 first), ``sectionNames`` (["Chapter", "Mishnah"]), and a
depth-2 ``text`` array: ``text[chapter_idx][mishnah_idx]`` -> a Hebrew string
with full nikkud and embedded inline HTML (<i>, <br>, and Vilna-page overlay
spans). Empty-string leaves are skipped (some tractates carry trailing blanks).

anchor_id = ``mishnah.<tractate-slug>.<chapter>.<mishnah>`` (1-indexed chapter
and mishnah). chunk_id == anchor_id. ``<tractate-slug>`` is the lowercase kebab
of the Sefaria English tractate name with any leading "Mishnah " removed
(e.g. "Mishnah Sanhedrin" -> "sanhedrin", "Pirkei Avot" -> "pirkei-avot").

Two source-specific disciplines per docs/HISTORICAL_SCHEMA.md and the catalog
required_flags:

  1. Inline HTML (<i>, <strong>, <big>, <br>, and <i data-overlay="Vilna Pages">
     overlay spans) is stripped before storing so it does not pollute the
     embedding signal. strip_html / collapse_ws from _common handle this.

  2. Version pinning: only the Public Domain Torat Emet 357 Hebrew is ingested.
     The chosen version title is recorded in the chunk ``edition`` field so the
     pinned edition is auditable.

PURITY: this module reads only files under HISTORICAL_DATA_ROOT / "mishnah".
No network, no subprocess, no dynamic import, no path literals outside
data/private/. Staging the Sefaria merged files into
data/private/historical/mishnah/ is a separate procurement step performed
outside this module.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator
from pathlib import Path

from ingest.historical._common import HISTORICAL_DATA_ROOT, collapse_ws, strip_html
from pipeline4.historical_schema import (
    ContestedInterpolation,
    HistoricalChunk,
    Provenance,
    WitnessSource,
)

SOURCE_SLUGS: tuple[str, ...] = ("mishnah",)

_SOURCE_TYPE = "jewish-rabbinic"
_LANGUAGE = "he"
_TRANSLATOR = None  # Hebrew source-language entry; no translator.
_AUTHOR = None  # Collective rabbinic redaction; no single author.
_DATE_WRITTEN = "c. 200 CE"
_LICENSE = "PD"
_REDISTRIBUTE = True
_ORIGINAL_LANGUAGE = "he"
_LOSS_STATUS = "complete"

_VERSION_TITLE = "Torat Emet 357"
_VERSION_SOURCE = "gs://sefaria-export/json/Mishnah (Torat Emet 357, Public Domain)"
_EDITION = f"Sefaria-Export merged.json [{_VERSION_TITLE}]; {_VERSION_SOURCE}"
_WITNESS_CHAIN = ("hebrew-torat-emet-357",)
_EXTANT_WITNESSES = (
    "Torat Emet 357 (vocalized Mishnah text) via Sefaria-Export",
)
_LICENSE_NOTE = (
    "Mishnah Hebrew via Torat Emet 357, Public Domain. Canonical original "
    "language witness; text_to_embed equals text under the original-language "
    "discipline."
)

# Deterministic ingest order: canonical seder order, then tractate. The slug is
# the lowercase kebab of the Sefaria English tractate name with any leading
# "Mishnah " removed; the Sefaria title is kept for the source directory and the
# work_title. Frozen so two runs produce a byte-identical mishnah.jsonl.
_TRACTATES: tuple[tuple[str, str], ...] = (
    # Seder Zeraim
    ("berakhot", "Mishnah Berakhot"),
    ("bikkurim", "Mishnah Bikkurim"),
    ("challah", "Mishnah Challah"),
    ("demai", "Mishnah Demai"),
    ("kilayim", "Mishnah Kilayim"),
    ("maaser-sheni", "Mishnah Maaser Sheni"),
    ("maasrot", "Mishnah Maasrot"),
    ("orlah", "Mishnah Orlah"),
    ("peah", "Mishnah Peah"),
    ("sheviit", "Mishnah Sheviit"),
    ("terumot", "Mishnah Terumot"),
    # Seder Moed
    ("beitzah", "Mishnah Beitzah"),
    ("chagigah", "Mishnah Chagigah"),
    ("eruvin", "Mishnah Eruvin"),
    ("megillah", "Mishnah Megillah"),
    ("moed-katan", "Mishnah Moed Katan"),
    ("pesachim", "Mishnah Pesachim"),
    ("rosh-hashanah", "Mishnah Rosh Hashanah"),
    ("shabbat", "Mishnah Shabbat"),
    ("shekalim", "Mishnah Shekalim"),
    ("sukkah", "Mishnah Sukkah"),
    ("taanit", "Mishnah Ta'anit"),
    ("yoma", "Mishnah Yoma"),
    # Seder Nashim
    ("gittin", "Mishnah Gittin"),
    ("ketubot", "Mishnah Ketubot"),
    ("kiddushin", "Mishnah Kiddushin"),
    ("nazir", "Mishnah Nazir"),
    ("nedarim", "Mishnah Nedarim"),
    ("sotah", "Mishnah Sotah"),
    ("yevamot", "Mishnah Yevamot"),
    # Seder Nezikin
    ("avodah-zarah", "Mishnah Avodah Zarah"),
    ("bava-batra", "Mishnah Bava Batra"),
    ("bava-kamma", "Mishnah Bava Kamma"),
    ("bava-metzia", "Mishnah Bava Metzia"),
    ("eduyot", "Mishnah Eduyot"),
    ("horayot", "Mishnah Horayot"),
    ("makkot", "Mishnah Makkot"),
    ("sanhedrin", "Mishnah Sanhedrin"),
    ("shevuot", "Mishnah Shevuot"),
    ("pirkei-avot", "Pirkei Avot"),
    # Seder Kodashim
    ("arakhin", "Mishnah Arakhin"),
    ("bekhorot", "Mishnah Bekhorot"),
    ("chullin", "Mishnah Chullin"),
    ("keritot", "Mishnah Keritot"),
    ("kinnim", "Mishnah Kinnim"),
    ("meilah", "Mishnah Meilah"),
    ("menachot", "Mishnah Menachot"),
    ("middot", "Mishnah Middot"),
    ("tamid", "Mishnah Tamid"),
    ("temurah", "Mishnah Temurah"),
    ("zevachim", "Mishnah Zevachim"),
    # Seder Tahorot
    ("kelim", "Mishnah Kelim"),
    ("makhshirin", "Mishnah Makhshirin"),
    ("mikvaot", "Mishnah Mikvaot"),
    ("negaim", "Mishnah Negaim"),
    ("niddah", "Mishnah Niddah"),
    ("oholot", "Mishnah Oholot"),
    ("oktzin", "Mishnah Oktzin"),
    ("parah", "Mishnah Parah"),
    ("tahorot", "Mishnah Tahorot"),
    ("tevul-yom", "Mishnah Tevul Yom"),
    ("yadayim", "Mishnah Yadayim"),
    ("zavim", "Mishnah Zavim"),
)


def _clean(raw: str) -> str:
    """Strip inline HTML, collapse whitespace, and NFC-normalize a leaf string.

    The Hebrew merged text carries <i> emphasis spans, <br> line breaks, and
    Vilna-page overlay spans (<i data-overlay="Vilna Pages" ...>). strip_html
    drops the markup while keeping visible text; collapse_ws folds the resulting
    newlines and runs of spaces; NFC keeps the nikkud composition stable so two
    runs hash identically.
    """
    return unicodedata.normalize("NFC", collapse_ws(strip_html(raw)))


def _parse_tractate(
    json_path: Path, slug: str, work_title: str
) -> Iterator[HistoricalChunk]:
    if not json_path.is_file():
        return
    data = json.loads(json_path.read_text(encoding="utf-8"))
    text = data.get("text")
    if not isinstance(text, list):
        return

    work_id = f"mishnah.{slug}"
    for chapter_idx, chapter in enumerate(text, start=1):
        if not isinstance(chapter, list):
            continue
        for mishnah_idx, leaf in enumerate(chapter, start=1):
            if not isinstance(leaf, str):
                continue
            cleaned = _clean(leaf)
            if not cleaned:
                continue
            anchor_id = f"mishnah.{slug}.{chapter_idx}.{mishnah_idx}"
            yield HistoricalChunk(
                chunk_id=anchor_id,
                source_type=_SOURCE_TYPE,
                source=WitnessSource(
                    source_slug="mishnah",
                    work_id=work_id,
                    work_title=work_title,
                    author=_AUTHOR,
                    date_written_range=_DATE_WRITTEN,
                    anchor_id=anchor_id,
                    anchor_alt_citation=None,
                    language=_LANGUAGE,
                    translator=_TRANSLATOR,
                    edition=_EDITION,
                ),
                contested_interpolation=ContestedInterpolation(),
                provenance=Provenance(
                    original_language=_ORIGINAL_LANGUAGE,
                    witness_chain=list(_WITNESS_CHAIN),
                    extant_witnesses=list(_EXTANT_WITNESSES),
                    loss_status=_LOSS_STATUS,
                ),
                text=cleaned,
                text_to_embed=cleaned,
                license=_LICENSE,
                redistribute=_REDISTRIBUTE,
                license_note=_LICENSE_NOTE,
            )


def parse() -> Iterator[HistoricalChunk]:
    """Parse the sixty-three Mishnah tractates in deterministic order.

    Order is fixed by _TRACTATES (canonical seder order, then tractate), then by
    chapter and mishnah index within each tractate, so two runs produce a
    byte-identical mishnah.jsonl. Tractates without a staged hebrew_merged.json
    are skipped silently (procurement runs separately).
    """
    root = HISTORICAL_DATA_ROOT / "mishnah"
    for slug, work_title in _TRACTATES:
        json_path = root / slug / "hebrew_merged.json"
        if not json_path.is_file():
            continue
        yield from _parse_tractate(json_path, slug, work_title)
