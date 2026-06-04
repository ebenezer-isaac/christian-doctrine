"""Pipeline 1 cultural Phase 03 runner: drive the cultural autotag end to end.

The autotag dispatcher (``ingest/cultural/autotag.py``) holds the per-batch
confidence routing logic. This module is the surrounding runner that the
orchestrator drives:

  1. ``build_batches`` reads every chunk in the cult_col Qdrant collection
     (``chunk_id`` + ``text`` only, no biasing metadata) and writes batch input
     files for the ``cultural_autotag`` subagents to read.
  2. The orchestrator dispatches one subagent per batch (Sonnet, the
     ``cultural_autotag`` phase prompt). Each writes
     ``tmp/cultural_autotag/<task>/tagged_chunks.jsonl``.
  3. ``collect_tags`` reads those jsonl files back, validates every tag against
     ``DoctrineTag``, applies the 0.6 confidence floor and the 5-tag cap.
  4. ``persist_qdrant`` writes the kept tags onto each cult_col point payload
     (``set_payload``), which is exactly where ``bd_mcp/live/cultural.py`` reads
     ``stance`` from. ``persist_neo4j`` mirrors them onto the CulturalChunk node
     so the graph and the vector store agree.

No re-embedding is needed: doctrine_tags are payload metadata, not part of the
dense vector (the chunk ``text_to_embed`` is unchanged).

Air-gap: cultural store ONLY (cult_col on QDRANT_CULTURAL_URL, cultural Neo4j).
Never the lexical store.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ingest.cultural._common import Settings, get_cultural_driver
from ingest.cultural.autotag import CONFIDENCE_THRESHOLD
from ingest.models import DoctrineTag

CULT_COLLECTION = "cult_col"
DEFAULT_BATCH_SIZE = 100
MAX_TAGS_PER_CHUNK = 5
BATCH_ROOT = Path("tmp/cultural_autotag")


# ---------------------------------------------------------------------------
# Qdrant client (cultural store only)
# ---------------------------------------------------------------------------


def _qdrant_client(settings: Settings | None = None, client: Any | None = None) -> Any:
    if client is not None:
        return client
    from qdrant_client import QdrantClient

    s = settings or Settings()  # type: ignore[call-arg]
    return QdrantClient(url=s.qdrant_cultural_url)


def iter_points(
    client: Any, collection: str = CULT_COLLECTION, page: int = 512
) -> Iterator[tuple[str, str, str]]:
    """Yield (point_id, chunk_id, text) for every point in the collection."""
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=page,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )
        for p in points:
            payload = p.payload or {}
            chunk_id = payload.get("chunk_id")
            text = payload.get("text", "")
            if chunk_id:
                yield str(p.id), str(chunk_id), str(text)
        if offset is None:
            break


# ---------------------------------------------------------------------------
# 1. Build batch input files
# ---------------------------------------------------------------------------


def build_batches(
    out_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    settings: Settings | None = None,
    client: Any | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Write batch input files of {chunk_id, text} for the autotag subagents.

    Returns a manifest dict {batch_dir, batch_count, total_chunks, batches:[paths]}.
    ``limit`` caps the number of chunks (for sample validation runs).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    qc = _qdrant_client(settings, client)
    rows: list[dict[str, str]] = []
    for _point_id, chunk_id, text in iter_points(qc):
        rows.append({"chunk_id": chunk_id, "text": text})
        if limit is not None and len(rows) >= limit:
            break

    batch_paths: list[str] = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        idx = i // batch_size
        path = out_dir / f"batch_{idx:04d}.json"
        path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
        batch_paths.append(str(path))

    manifest = {
        "batch_dir": str(out_dir),
        "batch_count": len(batch_paths),
        "total_chunks": len(rows),
        "batch_size": batch_size,
        "batches": batch_paths,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


# ---------------------------------------------------------------------------
# 3. Collect + validate tagged output
# ---------------------------------------------------------------------------


def _validate_tags(raw_tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate each tag against DoctrineTag, keep conf >= floor, cap at 5."""
    kept: list[dict[str, Any]] = []
    for raw in raw_tags or []:
        try:
            tag = DoctrineTag.model_validate(raw)
        except Exception:  # noqa: BLE001  a malformed tag is dropped, never persisted
            continue
        if tag.confidence < CONFIDENCE_THRESHOLD:
            continue
        kept.append(tag.model_dump())
    kept.sort(key=lambda t: float(t.get("confidence", 0.0)), reverse=True)
    return kept[:MAX_TAGS_PER_CHUNK]


def collect_tags(tagged_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Read every tagged_chunks.jsonl under tagged_dir, return {chunk_id: [tag dicts]}.

    Only chunks with at least one kept (>= 0.6) tag appear in the result.
    A chunk seen twice keeps the union, re-capped to the top 5 by confidence.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(tagged_dir.rglob("tagged_chunks.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk_id = rec.get("chunk_id")
            if not chunk_id:
                continue
            kept = _validate_tags(rec.get("doctrine_tags", []))
            if not kept:
                continue
            merged = out.get(str(chunk_id), []) + kept
            merged.sort(key=lambda t: float(t.get("confidence", 0.0)), reverse=True)
            out[str(chunk_id)] = merged[:MAX_TAGS_PER_CHUNK]
    return out


# ---------------------------------------------------------------------------
# 4. Persist
# ---------------------------------------------------------------------------


def persist_qdrant(
    tags_by_chunk: dict[str, list[dict[str, Any]]],
    settings: Settings | None = None,
    client: Any | None = None,
    page: int = 512,
) -> dict[str, int]:
    """Write doctrine_tags onto the cult_col point payloads (set_payload per point).

    bd_mcp/live/cultural.py reads stance from this payload, so this is the write
    that makes cultural stance attribution go live. Returns counts.
    """
    qc = _qdrant_client(settings, client)
    updated = 0
    scanned = 0
    for point_id, chunk_id, _text in iter_points(qc, page=page):
        scanned += 1
        tags = tags_by_chunk.get(chunk_id)
        if not tags:
            continue
        qc.set_payload(
            collection_name=CULT_COLLECTION,
            payload={"doctrine_tags": tags},
            points=[point_id],
        )
        updated += 1
    return {"scanned": scanned, "updated": updated, "chunks_with_tags": len(tags_by_chunk)}


_NEO4J_TAG_CYPHER = """
UNWIND $rows AS row
MATCH (c:CulturalChunk {chunk_id: row.chunk_id})
SET c.doctrine_tags = row.tags
RETURN count(c) AS updated
"""


def persist_neo4j(
    tags_by_chunk: dict[str, list[dict[str, Any]]],
    settings: Settings | None = None,
    driver: Any | None = None,
    batch_size: int = 500,
) -> dict[str, int]:
    """Mirror the kept tags onto CulturalChunk nodes (doctrine_tags as JSON strings).

    Matches the storage shape that ``_common.upsert_chunks`` uses, so the graph
    and the vector store agree.
    """
    own = driver is None
    drv = driver or get_cultural_driver(settings or Settings())  # type: ignore[call-arg]
    rows = [
        {"chunk_id": cid, "tags": [json.dumps(t, ensure_ascii=False) for t in tags]}
        for cid, tags in tags_by_chunk.items()
    ]
    updated = 0
    try:
        with drv.session() as session:
            for i in range(0, len(rows), batch_size):
                res = session.run(_NEO4J_TAG_CYPHER, rows=rows[i : i + batch_size]).single()
                updated += int(res["updated"]) if res else 0
    finally:
        if own:
            drv.close()
    return {"updated": updated}
