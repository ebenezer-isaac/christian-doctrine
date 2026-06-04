"""Shared helpers for Pipeline 1 historical adapters and the loader.

Provides:
  - HISTORICAL_DATA_ROOT / CHUNKS_OUT_DIR path anchors
  - HistoricalSettings (env-driven; reuses NEO4J_CULTURAL_* and QDRANT_CULTURAL_*)
  - get_historical_driver(settings) -> Driver  (cultural Docker stack)
  - write_chunks_jsonl(slug, chunks) -> Path   (data/historical_chunks/<slug>.jsonl)
  - read_chunks_jsonl(path) -> Iterator[HistoricalChunk]
  - upsert_historical_chunks(driver, chunks)   (HistoricalSource + HistoricalWork
        + HistoricalChunk + CONTAINS + HAS_CHUNK)
  - strip_html / collapse_ws text utilities

The adapter contract (every ingest/historical/<source>.py module):

    SOURCE_SLUGS: tuple[str, ...]          # slugs this adapter emits
    def parse() -> Iterator[HistoricalChunk]:
        '''Parse data/private/historical/<source>/ into HistoricalChunk records.
        Pure: reads only data/private files, performs no network or subprocess.'''

The loader (run.py) imports each adapter's ``parse`` and routes its records to
JSONL and, with --load, to Neo4j. No adapter writes to Neo4j or Qdrant directly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from neo4j import Driver, GraphDatabase
from pydantic_settings import BaseSettings, SettingsConfigDict

from ingest.license_guard import check_redistribute
from pipeline4.historical_schema import HistoricalChunk

# Source data lives under data/private (gitignored, adapter-pure path root).
HISTORICAL_DATA_ROOT = Path("data/private/historical")
# Parsed chunk JSONL output (mirrors data/cultural_chunks/ for the cultural side).
CHUNKS_OUT_DIR = Path("data/historical_chunks")


class HistoricalSettings(BaseSettings):
    """Connection settings for the historical layer (cultural Docker stack)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    neo4j_cultural_uri: str
    neo4j_cultural_user: str
    neo4j_cultural_password: str
    qdrant_cultural_url: str
    voyage_api_key: str = ""


def get_historical_driver(settings: HistoricalSettings) -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_cultural_uri,
        auth=(settings.neo4j_cultural_user, settings.neo4j_cultural_password),
    )


# ---------------------------------------------------------------------------
# Text utilities (adapters parse HTML / TEI / TSV; these are pure helpers)
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    def __init__(self, drop_tags: tuple[str, ...] = ("script", "style")) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._drop = drop_tags
        self._suppress = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._drop:
            self._suppress += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._drop and self._suppress > 0:
            self._suppress -= 1

    def handle_data(self, data: str) -> None:
        if self._suppress == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def strip_html(html: str, drop_tags: tuple[str, ...] = ("script", "style")) -> str:
    """Return visible text from an HTML fragment, dropping script/style by default."""
    parser = _TextExtractor(drop_tags=drop_tags)
    parser.feed(html)
    return parser.text()


_WS_RE = re.compile(r"\s+")


def collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# JSONL persistence (adapter output)
# ---------------------------------------------------------------------------


def write_chunks_jsonl(slug: str, chunks: Iterable[HistoricalChunk]) -> Path:
    """Write HistoricalChunk records to data/historical_chunks/<slug>.jsonl.

    Order-stable: callers should emit chunks in a deterministic order so two
    runs produce byte-identical files (h5_snapshot_determinism).
    """
    CHUNKS_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = CHUNKS_OUT_DIR / f"{slug}.jsonl"
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n")
            n += 1
    return out


def read_chunks_jsonl(path: Path) -> Iterator[HistoricalChunk]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield HistoricalChunk.model_validate(json.loads(line))


# ---------------------------------------------------------------------------
# Neo4j upsert (loader; HistoricalSource -> HistoricalWork -> HistoricalChunk)
# ---------------------------------------------------------------------------

_SOURCE_CYPHER = """
UNWIND $rows AS row
MERGE (s:HistoricalSource {slug: row.slug})
SET s.label = row.label, s.source_type = row.source_type
RETURN count(s) AS n
"""

_WORK_CYPHER = """
UNWIND $rows AS row
MERGE (w:HistoricalWork {work_id: row.work_id})
SET w += row.properties
WITH w, row
MATCH (s:HistoricalSource {slug: row.source_slug})
MERGE (s)-[:CONTAINS]->(w)
RETURN count(w) AS n
"""

_CHUNK_CYPHER = """
UNWIND $rows AS row
MERGE (c:HistoricalChunk {chunk_id: row.chunk_id})
SET c += row.properties
WITH c, row
MATCH (w:HistoricalWork {work_id: row.work_id})
MERGE (w)-[:HAS_CHUNK]->(c)
RETURN count(c) AS n
"""


def upsert_historical_chunks(
    driver: Driver, chunks: Iterable[HistoricalChunk], batch_size: int = 200
) -> dict[str, int]:
    """Upsert chunks to the historical store. License guard fail-closed on text.

    The copyright contract mirrors ingest/cultural/_common.upsert_chunks: the
    verbatim ``text`` is persisted only when the chunk license permits bulk
    redistribution; otherwise the redistribute-safe ``text_to_embed`` surface is
    persisted in its place (DSS under CC-BY-NC-4.0 falls here, but Option A makes
    text_to_embed == text for DSS anyway, so the transliteration is preserved).
    """
    counts: dict[str, int] = {"HistoricalSource": 0, "HistoricalWork": 0, "HistoricalChunk": 0}
    # Track source and work ids seen across the whole run so the reported tally
    # counts distinct nodes, not per-batch repeats (MERGE is idempotent, so a
    # source spanning many batches is one node, not one per batch).
    seen_sources: set[str] = set()
    seen_works: set[str] = set()
    batch: list[HistoricalChunk] = []

    def _flush(buf: list[HistoricalChunk]) -> None:
        if not buf:
            return
        sources: dict[str, dict[str, Any]] = {}
        works: dict[str, dict[str, Any]] = {}
        chunk_rows: list[dict[str, Any]] = []
        for c in buf:
            redistribute_ok = check_redistribute(c.license, "bulk")["allowed"]
            text_value = c.text if redistribute_ok else c.text_to_embed
            sources[c.source.source_slug] = {
                "slug": c.source.source_slug,
                "label": c.source.source_slug,
                "source_type": c.source_type,
            }
            works[c.source.work_id] = {
                "work_id": c.source.work_id,
                "source_slug": c.source.source_slug,
                "properties": {
                    "title": c.source.work_title,
                    "author": c.source.author,
                    "date_written_range": c.source.date_written_range,
                    "language": c.source.language,
                    "original_language": c.provenance.original_language,
                    "loss_status": c.provenance.loss_status,
                },
            }
            chunk_rows.append(
                {
                    "chunk_id": c.chunk_id,
                    "work_id": c.source.work_id,
                    "properties": {
                        "anchor_id": c.source.anchor_id,
                        "anchor_alt_citation": c.source.anchor_alt_citation,
                        "source_type": c.source_type,
                        "text": text_value,
                        "text_to_embed": c.text_to_embed,
                        "language": c.source.language,
                        "license": c.license,
                        "redistribute": c.redistribute,
                        "license_note": c.license_note,
                        "contested_interpolation_type": c.contested_interpolation.type,
                        "provenance_loss_status": c.provenance.loss_status,
                    },
                }
            )
        with driver.session() as session:
            session.run(_SOURCE_CYPHER, rows=list(sources.values())).consume()
            session.run(_WORK_CYPHER, rows=list(works.values())).consume()
            session.run(_CHUNK_CYPHER, rows=chunk_rows).consume()
        counts["HistoricalSource"] += len(set(sources) - seen_sources)
        counts["HistoricalWork"] += len(set(works) - seen_works)
        counts["HistoricalChunk"] += len(chunk_rows)
        seen_sources.update(sources)
        seen_works.update(works)

    for c in chunks:
        batch.append(c)
        if len(batch) >= batch_size:
            _flush(batch)
            batch = []
    _flush(batch)
    return counts
