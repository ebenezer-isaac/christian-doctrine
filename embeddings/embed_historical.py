"""Embed historical HistoricalChunks into Qdrant hist_col collection.

Reads JSONL chunk files from `data/historical_chunks/` (each line a
``pipeline4.historical_schema.HistoricalChunk`` dump produced by the
``ingest/historical/`` adapters), batches them through the Voyage embedding
API (voyage-4-large, 2048-dim), and upserts dense vectors into Qdrant.
Idempotent: each point uses the chunk_id as a deterministic id
(``uuid5(NS, chunk_id)``), and the target collection is dropped + recreated
ONCE at the start of the run (`_recreate_collection`, scoped strictly to
`--collection`, default `hist_col`) so hist_col deterministically mirrors the
current historical graph with zero stale orphan points across rebuilds.

This file mirrors ``embeddings/embed_cultural.py`` almost exactly: same Voyage
batching, same rate-limit posture, same recreate-once discipline, same
fail-closed license text gate.

Copyright contract (mirrors ``ingest/historical/_common.upsert_historical_chunks``
and the corrected cultural gate): the embed input is always the
redistribute-safe ``text_to_embed``, and the persisted Qdrant payload ``text``
is gated through ``ingest.license_guard.check_redistribute(license,"bulk")
["allowed"]`` (fail-closed) so verbatim copyrighted prose for a
redistribute=false source can never leak into hist_col. For DSS
(CC-BY-NC-4.0, redistribute=false) Option A makes ``text_to_embed == text``,
so the transliteration is preserved either way.

Rate-limit posture is identical to embed_cultural: BATCH=32 keeps every
request inside Voyage's per-request token cap; MIN_INTERVAL_SECONDS=0 because
the tier-1 RPM ceiling is far above what we can saturate; exponential-ish
backoff still kicks in on a 429 burst.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from embeddings.bootstrap import VOYAGE_MODEL, VOYAGE_OUTPUT_DIMENSION
from ingest.license_guard import check_redistribute

JSONL_DIR = Path("data/historical_chunks")
# Fresh namespace UUID for the historical layer (distinct from the cultural
# namespace so a chunk_id colliding across stores cannot collide on point id).
NS = uuid.UUID("b7c2d4e8-0000-4000-8000-000000000002")
# 32 keeps every batch inside Voyage's per-request token cap even for long
# leaves (e.g., a multi-section Josephus paragraph), matching embed_cultural.
BATCH = 32
MAX_TEXT_CHARS = 6000
MIN_INTERVAL_SECONDS = 0.0


def _chunks(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _redistribute_safe_text(chunk: dict[str, Any]) -> str:
    """Return the only payload text that is safe to persist in hist_col.

    Historical-store copyright contract (mirrors
    ``ingest/historical/_common.upsert_historical_chunks`` and the cultural
    gate): the verbatim ``text`` may be persisted ONLY when the chunk's
    license permits bulk redistribution. ``check_redistribute`` returns the
    ``RedistributeResult`` dict ``{"allowed": bool, "reason": str}``; a
    non-empty dict is always truthy, so the value MUST be read off the
    ``["allowed"]`` member (the exact dead-guard the Neo4j side leaked on).
    For a redistribute=false license (``CC-BY-NC-4.0`` Qumran sources,
    ``parsed-sanitized``, proprietary slugs ...) ``check_redistribute``
    returns ``allowed=False`` and we fall back to the redistribute-safe
    ``text_to_embed`` variant, never the copyrighted prose. Fail-closed: a
    missing/empty/unrecognized license is denied by the guard, so a malformed
    chunk yields ``text_to_embed`` (or empty), never the verbatim ``text``.
    For DSS under CC-BY-NC-4.0 Option A makes ``text_to_embed == text``
    anyway, so the transliteration is preserved while the gate stays closed.
    """
    license_str = chunk.get("license", "")
    if check_redistribute(license_str, "bulk")["allowed"]:
        return chunk.get("text", "")[:MAX_TEXT_CHARS]
    return chunk.get("text_to_embed", "")[:MAX_TEXT_CHARS]


def _point_for(chunk: dict[str, Any], vector: list[float]) -> PointStruct:
    """Build the hist_col PointStruct for one chunk + its dense vector.

    Payload follows docs/HISTORICAL_SCHEMA.md "Qdrant historical collection
    (hist_col) payload" exactly. ``doctrine_coarse_list`` /
    ``doctrine_fine_list`` / ``attestation_per_doctrine`` are the Pipeline 4
    ATTESTS output, NOT known at ingest/embed time, so they are seeded empty
    in v1 (``[]`` / ``[]`` / ``{}``) and back-filled by Pipeline 4. The
    redistribute-safe ``text`` is added for retrieval display only.
    """
    source = chunk["source"]
    contested = chunk.get("contested_interpolation") or {}
    payload: dict[str, Any] = {
        "chunk_id": chunk["chunk_id"],
        "source_slug": source["source_slug"],
        "source_type": chunk["source_type"],
        "work_id": source["work_id"],
        "anchor_id": source["anchor_id"],
        "doctrine_coarse_list": [],
        "doctrine_fine_list": [],
        "attestation_per_doctrine": {},
        "contested_interpolation_type": contested.get("type", "none"),
        "language": source["language"],
        "license": chunk["license"],
        "redistribute": chunk["redistribute"],
        # Retrieval-display text, fail-closed through the license guard.
        "text": _redistribute_safe_text(chunk),
    }
    point_id = str(uuid.uuid5(NS, chunk["chunk_id"]))
    return PointStruct(id=point_id, vector={"dense": vector}, payload=payload)


def _recreate_collection(qclient: Any, collection: str) -> None:
    """Drop and recreate exactly ``collection`` before any point is written.

    Deterministic-rebuild rationale, mirroring
    ``embeddings/embed_cultural._recreate_collection``: the embed run upserts
    points keyed by ``uuid5(NS, chunk_id)`` and ``upsert`` never deletes.
    Across historical-graph rebuilds a ``chunk_id`` that existed in a prior
    topology but not the current one leaves an orphaned stale vector behind
    that silently poisons retrieval. Recreating the collection here makes the
    embed deterministic and idempotent: after a run ``hist_col`` mirrors
    EXACTLY the current historical graph's embeddable chunk set with zero
    stale points, so two consecutive full runs on the same frozen graph yield
    the same point ids and the same points_count. This drop is scoped STRICTLY
    to the collection named by ``--collection`` (default ``hist_col``); no
    cultural collection and no lexical collection is read or touched. Vector
    config is held identical to ``embeddings.bootstrap`` (named vector
    ``"dense"``, size ``VOYAGE_OUTPUT_DIMENSION`` == 2048, COSINE distance) so
    retrieval semantics are unchanged.
    """
    existing = {c.name for c in qclient.get_collections().collections}
    if collection in existing:
        qclient.delete_collection(collection_name=collection)
    qclient.create_collection(
        collection_name=collection,
        vectors_config={
            "dense": VectorParams(
                size=VOYAGE_OUTPUT_DIMENSION, distance=Distance.COSINE
            )
        },
    )


def embed_file(
    path: Path,
    client: QdrantClient,
    voyage_client: Any,
    collection: str = "hist_col",
    rate_limit_state: dict[str, float] | None = None,
) -> dict[str, int]:
    count = 0
    failures = 0
    skipped_no_text = 0
    buffer: list[dict[str, Any]] = []
    state = rate_limit_state if rate_limit_state is not None else {"last": 0.0}

    def flush() -> None:
        nonlocal count, failures
        if not buffer:
            return
        now = time.monotonic()
        wait = MIN_INTERVAL_SECONDS - (now - state["last"])
        if wait > 0:
            time.sleep(wait)
        texts = [c["text_to_embed"][:MAX_TEXT_CHARS] for c in buffer]
        retries = 0
        while True:
            try:
                result = voyage_client.embed(
                    texts=texts,
                    model=VOYAGE_MODEL,
                    input_type="document",
                    output_dimension=VOYAGE_OUTPUT_DIMENSION,
                )
                break
            except Exception as exc:
                msg = str(exc)
                if retries < 3 and ("rate" in msg.lower() or "429" in msg or "TPM" in msg):
                    backoff = 30 * (retries + 1)
                    print(f"  rate-limit backoff {backoff}s", file=sys.stderr)
                    time.sleep(backoff)
                    retries += 1
                    continue
                print(f"  voyage error: {msg[:200]}", file=sys.stderr)
                failures += len(buffer)
                buffer.clear()
                state["last"] = time.monotonic()
                return
        points = [_point_for(c, vec) for c, vec in zip(buffer, result.embeddings, strict=False)]
        client.upsert(collection_name=collection, points=points)
        count += len(points)
        state["last"] = time.monotonic()
        buffer.clear()

    for chunk in _chunks(path):
        # Pre-filter textless chunks BEFORE they reach a Voyage batch. Voyage
        # rejects any request whose input list contains an empty string and
        # fails the WHOLE batch, dropping good chunks as collateral. The embed
        # input is always the redistribute-safe ``text_to_embed``; a chunk
        # with no embeddable text has nothing to re-rank on, so skipping it is
        # correct, not a fudge. Skips are counted, never silently dropped,
        # never sent to Voyage.
        text = chunk.get("text_to_embed", "")
        if not text or not text.strip():
            skipped_no_text += 1
            continue
        buffer.append(chunk)
        if len(buffer) >= BATCH:
            flush()
    flush()
    return {
        "embedded": count,
        "skipped_no_text": skipped_no_text,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sources",
        default="all",
        help="Comma-separated source slugs, or 'all'",
    )
    parser.add_argument("--collection", default="hist_col")
    args = parser.parse_args(argv)

    voyage_api_key = os.environ.get("VOYAGE_API_KEY")
    if not voyage_api_key:
        print("VOYAGE_API_KEY not set", file=sys.stderr)
        return 2
    qdrant_url = os.environ.get("QDRANT_CULTURAL_URL")
    if not qdrant_url:
        print("QDRANT_CULTURAL_URL not set", file=sys.stderr)
        return 2

    import voyageai

    voyage_client = voyageai.Client(api_key=voyage_api_key)  # type: ignore[attr-defined]
    qclient = QdrantClient(url=qdrant_url)

    # Rebuild the target collection ONCE, BEFORE any file is embedded, so the
    # run is deterministic and idempotent: hist_col ends mirroring exactly the
    # current historical graph's embeddable chunk set, with zero cross-rebuild
    # stale points. This is OUTSIDE the per-source loop on purpose: recreating
    # per file would wipe every previously embedded source. Scoped to
    # args.collection only; never touches the cultural or lexical collection.
    _recreate_collection(qclient, args.collection)

    if args.sources == "all":
        files = sorted(JSONL_DIR.glob("*.jsonl"))
    else:
        files = [JSONL_DIR / f"{s.strip()}.jsonl" for s in args.sources.split(",") if s.strip()]

    total = {"embedded": 0, "skipped_no_text": 0, "failures": 0}
    rate_state: dict[str, float] = {"last": 0.0}
    for path in files:
        if not path.exists():
            print(f"skip missing: {path}")
            continue
        t0 = time.monotonic()
        counts = embed_file(path, qclient, voyage_client, args.collection, rate_state)
        elapsed = round(time.monotonic() - t0, 1)
        print(
            f"{path.stem}: embedded={counts['embedded']} "
            f"skipped_no_text={counts['skipped_no_text']} "
            f"failures={counts['failures']} ({elapsed}s)",
            flush=True,
        )
        total["embedded"] += counts["embedded"]
        total["skipped_no_text"] += counts["skipped_no_text"]
        total["failures"] += counts["failures"]
    print(f"TOTAL: {json.dumps(total)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
