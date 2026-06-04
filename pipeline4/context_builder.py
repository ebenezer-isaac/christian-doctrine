"""Build the historical context bundle that Pipeline 4 subagents consume.

Queries the historical store (HistoricalSource | HistoricalWork |
HistoricalChunk | ATTESTS, on the cultural Docker stack) plus the read-only
locked lexical verdict from evidence/<question_id>.json. No cultural-overlay
chunk is ever read. The output shape matches the "Inputs" contract in
docs/phase_prompts/pipeline4_attestation.md.

ATTESTS edges are a Pipeline 4 OUTPUT, so they do not exist at build time.
Candidate retrieval is therefore two pre-attestation paths over neutral
HistoricalChunk nodes:

  (a) Qdrant hist_col dense semantic search on the question statement plus its
      scripture anchors (voyage-4-large query embedding), and
  (b) a named-entity keyword match over HistoricalChunk.text in Neo4j for the
      contested historical entities the question mentions.

The union is deduped by chunk_id and capped. Most questions return ZERO
candidates, which is correct: only a minority of the 231 questions have any
extra-biblical historical attestation in v1. Every store access is lazy and
defensive so a question with no anchors, or empty or unreachable stores,
returns an empty candidate list instead of crashing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = REPO_ROOT / "questions.json"
EVIDENCE_DIR = REPO_ROOT / "evidence"

# The seven source_type values in hist_col. Candidate retrieval runs one
# type-scoped dense search per value so no single tradition (DSS alone is
# ~73% of the ~62k chunks) crowds out the rest by raw volume. Every tradition
# is kept; the output is balanced, not trimmed.
SOURCE_TYPES: tuple[str, ...] = (
    "jewish-historian",
    "jewish-philosopher",
    "second-temple-literature",
    "roman-historian",
    "jewish-rabbinic",
    "qumran-sectarian",
    "qumran-biblical",
)

# Per-source-type dense quota. No single source_type may contribute more than
# this many chunks from the dense path, so a high-volume tradition cannot
# dominate the candidate set. 7 types x 6 = 42 dense slots before dedupe.
PER_TYPE_LIMIT = 6

# Overall cap on the deduped candidate set (7 types x 8 leaves headroom for the
# Neo4j keyword-recall path on top of the 42 balanced dense slots). Most
# questions land well under this; the cap only bounds the rare
# attestation-rich question (resurrection, census, etc.).
CANDIDATE_LIMIT = 56
KEYWORD_LIMIT = 30
HIST_COLLECTION = "hist_col"

# Named historical entities that recur in the contested-attestation questions.
# A question whose statement or scripture-anchor neighbourhood mentions one of
# these is a candidate for keyword retrieval over HistoricalChunk.text. The
# list is deliberately conservative: it surfaces the witnesses the prompt names
# (Quirinius, John the Baptist, Theudas, Lysanias, Pilate, Herod, census,
# resurrection, Sanhedrin) plus the obvious sibling terms.
_NAMED_ENTITIES: tuple[str, ...] = (
    "Quirinius",
    "Cyrenius",
    "census",
    "John the Baptist",
    "the Baptist",
    "Theudas",
    "Lysanias",
    "Pilate",
    "Pontius Pilate",
    "Herod",
    "Herodias",
    "resurrection",
    "Sanhedrin",
    "Caiaphas",
    "Annas",
    "Christ",
    "Christus",
    "Chrestus",
    "Tiberius",
    "Nazareth",
    "crucified",
    "crucifixion",
    "Messiah",
)


def load_question(question_id: str) -> dict[str, Any]:
    """Load one question entry from questions.json (top-level 'questions' list)."""
    raw = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    for q in raw["questions"]:
        if q["id"] == question_id:
            return q  # type: ignore[no-any-return]
    raise KeyError(f"question id {question_id!r} not in questions.json")


def _load_lexical_verdict_context(question_id: str) -> dict[str, Any]:
    """Read evidence/<question_id>.json as READ-ONLY context.

    Returns the verdict_summary (affirms, lexical_directness, rationale) and the
    scripture anchors the verdict relied on. Defensive: a missing or malformed
    evidence file yields a degraded but valid context block rather than a crash,
    because Pipeline 4 must not be blocked on the lexical sidecar being present.
    """
    path = EVIDENCE_DIR / f"{question_id}.json"
    verdict_summary: dict[str, Any] = {
        "affirms": None,
        "lexical_directness": None,
        "rationale": "",
    }
    scripture_anchors: list[str] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        verdict = raw.get("verdict") or {}
        verdict_summary = {
            "affirms": verdict.get("affirms"),
            "lexical_directness": verdict.get("lexical_directness"),
            "rationale": verdict.get("rationale", ""),
        }
        lexical = raw.get("lexical_evidence") or {}
        for entry in lexical.get("scripture") or []:
            ref = entry.get("ref") if isinstance(entry, dict) else None
            if isinstance(ref, str) and ref:
                scripture_anchors.append(ref)
    return {
        "schema_ref": "docs/EVIDENCE_SCHEMA.md",
        "verdict_summary": verdict_summary,
        "scripture_anchors": scripture_anchors,
        "read_only": True,
    }


def _question_entities(question: dict[str, Any]) -> list[str]:
    """Named entities (from _NAMED_ENTITIES) that appear in the question text.

    Case-insensitive substring match against the statement, category, and
    subcategory. Returns the entities in their canonical casing, deduped and
    order-stable, so keyword retrieval is deterministic.
    """
    haystack_parts = [
        str(question.get("statement", "")),
        str(question.get("category", "")),
        str(question.get("subcategory", "")),
    ]
    haystack = " ".join(haystack_parts).lower()
    found: list[str] = []
    for entity in _NAMED_ENTITIES:
        if entity.lower() in haystack and entity not in found:
            found.append(entity)
    return found


def _semantic_query_text(question: dict[str, Any], lexical_ctx: dict[str, Any]) -> str:
    """Compose the dense-search query string from statement plus scripture anchors."""
    parts: list[str] = [str(question.get("statement", "")).strip()]
    anchors = list(question.get("scripture_anchors", []) or [])
    anchors.extend(lexical_ctx.get("scripture_anchors", []) or [])
    seen: set[str] = set()
    for a in anchors:
        a_str = str(a).strip()
        if a_str and a_str not in seen:
            seen.add(a_str)
            parts.append(a_str)
    return " ".join(p for p in parts if p).strip()


def _candidate_from_payload(payload: dict[str, Any], chunk_id: str) -> dict[str, Any] | None:
    """Normalize a Qdrant hist_col payload into a candidate_chunk dict."""
    if not chunk_id:
        return None
    return {
        "chunk_id": chunk_id,
        "source_type": payload.get("source_type", ""),
        "source_slug": payload.get("source_slug", ""),
        "work_id": payload.get("work_id", ""),
        "anchor_id": payload.get("anchor_id", ""),
        "text": payload.get("text", ""),
        "text_to_embed": payload.get("text_to_embed", payload.get("text", "")),
        "language": payload.get("language", ""),
        "license": payload.get("license", ""),
        "redistribute": bool(payload.get("redistribute", False)),
        "contested_interpolation_type": payload.get(
            "contested_interpolation_type", "none"
        ),
        "provenance_loss_status": payload.get("provenance_loss_status", ""),
    }


def _candidate_from_neo4j(record: dict[str, Any]) -> dict[str, Any] | None:
    chunk_id = record.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id:
        return None
    return {
        "chunk_id": chunk_id,
        "source_type": record.get("source_type", ""),
        "source_slug": record.get("source_slug", ""),
        "work_id": record.get("work_id", ""),
        "anchor_id": record.get("anchor_id", ""),
        "text": record.get("text", ""),
        "text_to_embed": record.get("text_to_embed", record.get("text", "")),
        "language": record.get("language", ""),
        "license": record.get("license", ""),
        "redistribute": bool(record.get("redistribute", False)),
        "contested_interpolation_type": record.get(
            "contested_interpolation_type", "none"
        ),
        "provenance_loss_status": record.get("provenance_loss_status", ""),
    }


def _points_to_candidates(points: Any) -> list[dict[str, Any]]:
    """Normalize a list of Qdrant points into candidate_chunk dicts."""
    out: list[dict[str, Any]] = []
    for p in points or []:
        payload = dict(getattr(p, "payload", None) or {})
        chunk_id = payload.get("chunk_id") or str(getattr(p, "id", "") or "")
        candidate = _candidate_from_payload(payload, chunk_id)
        if candidate is not None:
            out.append(candidate)
    return out


def _dense_candidates_by_type(
    settings: Any, query_text: str
) -> dict[str, list[dict[str, Any]]]:
    """Source-type-balanced dense search over Qdrant hist_col. Empty on failure.

    Runs one dense search per source_type, each FILTERED to that type and
    capped at PER_TYPE_LIMIT, and returns a mapping source_type -> hits. This
    keeps every tradition fairly represented in the candidate set even though
    one source_type (DSS) holds the large majority of the chunks. The balancing
    decision itself lives in the pure helper balance_candidates so it is unit
    testable without a live Qdrant.

    Lazy and fail-soft: a missing voyage key, an unreachable Qdrant, or an
    absent hist_col collection all degrade to an empty mapping. The query
    embedding is computed ONCE and reused across all seven type-scoped searches.
    This is the path that does not exist without Docker, and it must never raise.
    """
    if not query_text:
        return {}
    voyage_key = getattr(settings, "voyage_api_key", "") or ""
    qdrant_url = getattr(settings, "qdrant_cultural_url", "") or ""
    if not voyage_key or not qdrant_url:
        return {}
    try:
        import voyageai
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from embeddings.bootstrap import VOYAGE_MODEL, VOYAGE_OUTPUT_DIMENSION

        voyage_client = voyageai.Client(api_key=voyage_key)  # type: ignore[attr-defined]
        embed = voyage_client.embed(
            texts=[query_text],
            model=VOYAGE_MODEL,
            input_type="query",
            output_dimension=VOYAGE_OUTPUT_DIMENSION,
        )
        vector = [float(x) for x in embed.embeddings[0]]
        client = QdrantClient(url=qdrant_url)
    except Exception:
        return {}

    by_type: dict[str, list[dict[str, Any]]] = {}
    for source_type in SOURCE_TYPES:
        try:
            points = client.query_points(
                collection_name=HIST_COLLECTION,
                query=vector,
                using="dense",
                limit=PER_TYPE_LIMIT,
                with_payload=True,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="source_type",
                            match=MatchValue(value=source_type),
                        )
                    ]
                ),
            ).points
        except Exception:
            # One type failing (e.g. transient) must not sink the others.
            continue
        hits = _points_to_candidates(points)
        if hits:
            by_type[source_type] = hits
    return by_type


_KEYWORD_CYPHER = """
UNWIND $terms AS term
MATCH (s:HistoricalSource)-[:CONTAINS]->(w:HistoricalWork)-[:HAS_CHUNK]->(c:HistoricalChunk)
WHERE toLower(c.text) CONTAINS toLower(term)
WITH DISTINCT c, w, s
RETURN c.chunk_id AS chunk_id,
       coalesce(c.source_type, s.source_type, '') AS source_type,
       coalesce(s.slug, '') AS source_slug,
       coalesce(w.work_id, '') AS work_id,
       coalesce(c.anchor_id, '') AS anchor_id,
       coalesce(c.text, '') AS text,
       coalesce(c.text_to_embed, c.text, '') AS text_to_embed,
       coalesce(c.language, '') AS language,
       coalesce(c.license, '') AS license,
       coalesce(c.redistribute, false) AS redistribute,
       coalesce(c.contested_interpolation_type, 'none') AS contested_interpolation_type,
       coalesce(c.provenance_loss_status, '') AS provenance_loss_status
ORDER BY chunk_id
LIMIT $limit
"""


def _keyword_candidates(settings: Any, entities: list[str]) -> list[dict[str, Any]]:
    """Named-entity keyword match over HistoricalChunk.text in Neo4j. Empty on failure.

    Lazy and fail-soft: an unreachable Neo4j or an empty historical graph yields
    zero candidates rather than raising. This is the path that does not exist
    without Docker.
    """
    if not entities:
        return []
    try:
        from ingest.historical._common import (
            HistoricalSettings,
            get_historical_driver,
        )

        hist_settings = settings
        if not isinstance(settings, HistoricalSettings):
            hist_settings = HistoricalSettings()  # type: ignore[call-arg]
        driver = get_historical_driver(hist_settings)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    try:
        with driver.session() as session:
            result = session.run(_KEYWORD_CYPHER, terms=entities, limit=KEYWORD_LIMIT)
            for rec in result:
                candidate = _candidate_from_neo4j(dict(rec))
                if candidate is not None:
                    out.append(candidate)
    except Exception:
        out = []
    finally:
        try:
            driver.close()
        except Exception:
            pass
    return out


def balance_candidates(
    dense_by_type: dict[str, list[dict[str, Any]]],
    keyword: list[dict[str, Any]] | None = None,
    per_type_limit: int = PER_TYPE_LIMIT,
    overall_limit: int = CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    """Pure source-type-balancing of dense hits plus the keyword-recall path.

    Given a mapping source_type -> list_of_dense_hits (already ordered by
    relevance per type) and an optional flat keyword-recall list, produce one
    deduped candidate list where:

      - NO source_type contributes more than per_type_limit chunks from the
        dense path, so a high-volume tradition (DSS) cannot dominate by raw
        volume. A lopsided input (e.g. 100 DSS hits, 2 Josephus hits) yields a
        balanced output: DSS is capped at per_type_limit and Josephus is fully
        retained.
      - candidates are deduped by chunk_id (first occurrence wins).
      - the keyword path is unioned on top (a useful recall route) and is NOT
        subject to the per-type cap, since it is a small entity-match set.
      - the result is capped at overall_limit.

    Pure and side-effect-free: no I/O, no Qdrant, no Neo4j. Unknown source_type
    keys are still capped at per_type_limit and included, so an unexpected type
    cannot dominate either. Input lists are never mutated.
    """
    capped_dense: list[dict[str, Any]] = []
    # Iterate the canonical SOURCE_TYPES first for deterministic ordering, then
    # any extra keys present in the mapping (defensive, order-stable).
    ordered_types = list(SOURCE_TYPES) + [
        t for t in dense_by_type if t not in SOURCE_TYPES
    ]
    for source_type in ordered_types:
        hits = dense_by_type.get(source_type) or []
        for cand in hits[:per_type_limit]:
            capped_dense.append(cand)

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for candidates in (capped_dense, keyword or []):
        for cand in candidates:
            chunk_id = cand.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            out.append(cand)
            if len(out) >= overall_limit:
                return out
    return out


def build_historical_context_bundle(
    question_id: str, settings: Any | None = None
) -> dict[str, Any]:
    """Construct the Pipeline 4 historical inputs bundle for one question.

    Returns the full "Inputs" dict from docs/phase_prompts/pipeline4_attestation.md
    minus task_id and output_path (those are filled by the dispatcher). The
    candidate_chunks list is the source-type-balanced union of dense (Qdrant
    hist_col, one quota-capped search per source_type) and named-entity keyword
    (Neo4j) retrieval, deduped by chunk_id and capped. No single source_type can
    dominate the dense path by raw volume. Most questions return an empty
    candidate_chunks list, which is correct.
    """
    question = load_question(question_id)
    lexical_ctx = _load_lexical_verdict_context(question_id)

    if settings is None:
        try:
            from ingest.historical._common import HistoricalSettings

            settings = HistoricalSettings()  # type: ignore[call-arg]
        except Exception:
            settings = None

    dense_by_type: dict[str, list[dict[str, Any]]] = {}
    keyword: list[dict[str, Any]] = []
    if settings is not None:
        query_text = _semantic_query_text(question, lexical_ctx)
        entities = _question_entities(question)
        dense_by_type = _dense_candidates_by_type(settings, query_text)
        keyword = _keyword_candidates(settings, entities)

    candidate_chunks = balance_candidates(dense_by_type, keyword)

    return {
        "phase": "pipeline4_attestation",
        "question_id": question_id,
        "question_statement": question.get("statement", ""),
        "question_metadata": {
            "category": question.get("category"),
            "subcategory": question.get("subcategory"),
            "kind": question.get("kind"),
            "scripture_anchors": question.get("scripture_anchors", []),
            "brethren_distinctive": question.get("brethren_distinctive", False),
        },
        "lexical_verdict_context": lexical_ctx,
        "historical_context_bundle": {
            "candidate_chunks": candidate_chunks,
        },
        "schema_version": "1.0",
    }
