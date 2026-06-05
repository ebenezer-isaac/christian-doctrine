"""Live cultural-store retrieval injector for the Pipeline 3 MCP tools.

The cultural tool handlers (``cultural_overlay`` and ``debate_for_verse``) are
pure: each takes ``cultural_chunks`` injected and never opens a connection. This
module is the injector. It runs a dense semantic search over the Qdrant
``cult_col`` collection (voyage-4-large query embedding, mirroring the
``hist_col`` path in ``pipeline4/context_builder.py``), filtered by tradition and
optionally narrowed to the doctrine slug of a matched ``questions.json`` entry,
and returns chunks shaped EXACTLY as the two handlers expect:

    {tradition, source, stance, text, license, redistribute,
     source_work_word_count}

The handler does the license-aware snippet redaction downstream; this module
returns the full ``text`` plus metadata and never redacts.

Air-gap (hard): the cultural layer touches the cultural store ONLY. It connects
to ``QDRANT_CULTURAL_URL`` (cult_col on :7101) and, when a doctrine slug is
resolved, to the cultural Neo4j (``NEO4J_CULTURAL_URI``, bolt://localhost:7689)
to read the question -> doctrine slug edge. It NEVER connects to the lexical
store (:7688 / :7100). Cultural material is diagnostic; it never adjudicates a
verdict.

Graceful degradation (mirrors ``context_builder.py``): a missing voyage key, an
unreachable Qdrant, an absent collection, or an empty store all degrade to an
empty list instead of raising. Every store access is lazy and defensive.

cult_col payload note: the embedded payload (see ``embeddings/embed_cultural.py``)
carries ``tradition``, ``text``, ``license``, ``redistribute``, ``work_id``,
``work_title``, ``author``, ``date_written``, ``anchor_id`` and a
``doctrine_tags`` array. It does NOT carry a top-level ``stance`` or a
``source_work_word_count``. ``stance`` is derived from the matching doctrine tag
when the autotag pass has populated it (else None); ``source`` is the
``work_title`` (falling back to ``work_id``); ``source_work_word_count`` is not
stored, so a conservative default is supplied that lets the handler's standard
100-word fair-use cap govern redistribute=false snippets.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
QUESTIONS_PATH = REPO_ROOT / "questions.json"

CULT_COLLECTION = "cult_col"
DENSE_VECTOR_NAME = "dense"

# Not stored on the cult_col payload. A large default means the handler's
# one-percent cap (source_work_word_count // 100) lands above the 100-word
# SNIPPET_WORD_CAP, so the standard fair-use cap governs redistribute=false
# snippets instead of an over-tight per-work cap. Redistribute=true chunks are
# returned in full regardless of this value.
DEFAULT_SOURCE_WORK_WORD_COUNT = 100_000

# The 12 registered cultural traditions plus the escape hatch (CULTURAL_SCHEMA).
KNOWN_TRADITIONS: frozenset[str] = frozenset(
    {
        "patristic",
        "catholic-magisterial",
        "eastern-orthodox",
        "oriental-orthodox",
        "lutheran",
        "reformed",
        "anglican",
        "methodist",
        "anabaptist",
        "pentecostal",
        "plymouth-brethren",
        "other",
    }
)


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return s or "unknown"


def _load_question(question_id: str) -> dict[str, Any] | None:
    """Load one question entry from questions.json, or None if absent/unreadable."""
    if not QUESTIONS_PATH.exists():
        return None
    try:
        raw = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    entries = raw.get("questions") if isinstance(raw, dict) else raw
    for q in entries or []:
        if isinstance(q, dict) and q.get("id") == question_id:
            return q
    return None


def resolve_doctrine_slug(question: dict[str, Any]) -> str | None:
    """Resolve a question entry to its fine doctrine slug.

    Reuses the explicit, deterministic category -> fine-slug map that seeds the
    UNDER_QUESTION edges in the cultural Neo4j, so the doctrine narrowing here
    agrees exactly with the graph linkage. Returns None when the category is
    absent or unmapped rather than raising, so retrieval degrades to a
    tradition-only dense search instead of failing.
    """
    category = question.get("category")
    if not category:
        return None
    try:
        from ingest.cultural.seed_doctrine_question_nodes import _resolve_fine_slug

        return _resolve_fine_slug(str(category))
    except Exception:
        return None


def _normalize_traditions(traditions: list[str] | None) -> list[str]:
    """Lowercase, slugify, dedupe and keep only registered tradition slugs."""
    if not traditions:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for t in traditions:
        slug = _slugify(str(t))
        if slug in KNOWN_TRADITIONS and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _query_text(doctrine: str | None, ref: str | None, doctrine_slug: str | None) -> str:
    """Compose the dense-search query from doctrine, ref and resolved slug."""
    parts: list[str] = []
    for piece in (doctrine, ref, doctrine_slug):
        piece_str = str(piece).strip() if piece is not None else ""
        if piece_str and piece_str not in parts:
            parts.append(piece_str)
    return " ".join(parts).strip()


def _stance_for_slug(doctrine_tags: Any, doctrine_slug: str | None) -> str | None:
    """Best stance from a chunk's doctrine_tags for the target slug.

    The tags array is empty until the cultural autotag pass runs, so this
    returns None for an untagged chunk, which is correct: we never invent a
    stance. When tags are present, prefer the tag whose doctrine_fine matches the
    target slug (highest confidence wins); otherwise fall back to the highest
    confidence tag present. Each tag is a dict (Qdrant) or a JSON string (the
    Neo4j projection); both are handled.
    """
    tags = _coerce_tags(doctrine_tags)
    if not tags:
        return None
    matching = [t for t in tags if t.get("doctrine_fine") == doctrine_slug] if doctrine_slug else []
    pool = matching or tags

    def _conf(tag: dict[str, Any]) -> float:
        try:
            return float(tag.get("confidence", 0.0))
        except (TypeError, ValueError):
            return 0.0

    best = max(pool, key=_conf)
    stance = best.get("stance")
    return str(stance) if stance else None


def _coerce_tags(doctrine_tags: Any) -> list[dict[str, Any]]:
    """Normalize doctrine_tags (list of dicts or list of JSON strings) to dicts."""
    out: list[dict[str, Any]] = []
    for entry in doctrine_tags or []:
        if isinstance(entry, dict):
            out.append(entry)
        elif isinstance(entry, str):
            try:
                parsed = json.loads(entry)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
    return out


def _chunk_from_payload(payload: dict[str, Any], doctrine_slug: str | None) -> dict[str, Any]:
    """Map a cult_col payload to the exact shape the cultural handlers expect."""
    work_title = payload.get("work_title") or payload.get("work_id") or "<unknown>"
    return {
        "tradition": payload.get("tradition"),
        "source": work_title,
        "stance": _stance_for_slug(payload.get("doctrine_tags"), doctrine_slug),
        "text": payload.get("text", ""),
        "license": payload.get("license", "<unknown>"),
        "redistribute": bool(payload.get("redistribute", False)),
        "source_work_word_count": int(
            payload.get("source_work_word_count", DEFAULT_SOURCE_WORK_WORD_COUNT)
        ),
        # Diagnostic metadata the handlers may surface; ignored if unused.
        "chunk_id": payload.get("chunk_id"),
        "anchor_id": payload.get("anchor_id"),
        "work_id": payload.get("work_id"),
    }


def _build_tradition_filter(traditions: list[str]) -> Any | None:
    """Qdrant filter matching any of the given tradition slugs, or None."""
    if not traditions:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    return Filter(must=[FieldCondition(key="tradition", match=MatchAny(any=list(traditions)))])


def _dense_search(
    qdrant_url: str,
    voyage_key: str,
    query_text: str,
    traditions: list[str],
    limit: int,
    qdrant_client: Any | None = None,
    voyage_client: Any | None = None,
) -> list[dict[str, Any]]:
    """Dense search over cult_col. Returns payload dicts. Empty on any failure.

    Lazy and fail-soft: a missing voyage key or qdrant url, an unreachable
    Qdrant, or an absent collection all degrade to an empty list. Clients may be
    injected for tests; otherwise they are constructed here.
    """
    if not query_text:
        return []
    if voyage_client is None and not voyage_key:
        return []
    if qdrant_client is None and not qdrant_url:
        return []
    try:
        from embeddings.bootstrap import VOYAGE_MODEL, VOYAGE_OUTPUT_DIMENSION

        if voyage_client is None:
            import voyageai

            voyage_client = voyageai.Client(api_key=voyage_key)  # type: ignore[attr-defined]
        embed = voyage_client.embed(
            texts=[query_text],
            model=VOYAGE_MODEL,
            input_type="query",
            output_dimension=VOYAGE_OUTPUT_DIMENSION,
        )
        vector = [float(x) for x in embed.embeddings[0]]

        if qdrant_client is None:
            from qdrant_client import QdrantClient

            qdrant_client = QdrantClient(url=qdrant_url)

        points = qdrant_client.query_points(
            collection_name=CULT_COLLECTION,
            query=vector,
            using=DENSE_VECTOR_NAME,
            limit=limit,
            with_payload=True,
            query_filter=_build_tradition_filter(traditions),
        ).points
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for p in points or []:
        payload = dict(getattr(p, "payload", None) or {})
        if payload:
            out.append(payload)
    return out


def build_cultural_clients(
    settings: Any | None = None,
) -> tuple[Any | None, Any | None]:
    """Construct the cultural Qdrant client and the voyage client, or (None, None).

    Built once at server startup and reused across requests (the FastMCP lifespan
    holds them). Fail-soft: a missing url or key, or an unavailable dependency,
    yields None for that client and the cultural overlay degrades to empty.
    Air-gap: reads only the cultural Qdrant url and the voyage key.
    """
    if settings is None:
        try:
            from retrieval.hybrid import RetrievalSettings

            settings = RetrievalSettings()
        except Exception:
            return None, None
    qdrant_url = getattr(settings, "qdrant_cultural_url", "") or ""
    voyage_key = getattr(settings, "voyage_api_key", "") or ""

    qdrant_client: Any | None = None
    if qdrant_url:
        try:
            from qdrant_client import QdrantClient

            qdrant_client = QdrantClient(url=qdrant_url)
        except Exception:
            qdrant_client = None

    voyage_client: Any | None = None
    if voyage_key:
        try:
            import voyageai

            voyage_client = voyageai.Client(api_key=voyage_key)  # type: ignore[attr-defined]
        except Exception:
            voyage_client = None

    return qdrant_client, voyage_client


def retrieve_cultural_chunks(
    doctrine: str | None = None,
    ref: str | None = None,
    traditions: list[str] | None = None,
    k: int = 8,
    question_id: str | None = None,
    settings: Any | None = None,
    qdrant_client: Any | None = None,
    voyage_client: Any | None = None,
) -> list[dict[str, Any]]:
    """Retrieve cultural chunks for a doctrine or verse, shaped for the handlers.

    Returns up to ``k`` chunk dicts, each with the EXACT keys the cultural
    handlers expect: ``tradition``, ``source``, ``stance``, ``text``,
    ``license``, ``redistribute``, ``source_work_word_count`` (plus diagnostic
    ``chunk_id`` / ``anchor_id`` / ``work_id`` that the handlers ignore). The
    handler enforces the snippet caps downstream; this returns full ``text``.

    Retrieval is a dense voyage-4-large semantic search over cult_col, filtered
    to ``traditions`` (any registered tradition slug; unknown slugs are dropped)
    and queried with the doctrine, ref, and resolved doctrine slug. When
    ``question_id`` matches a ``questions.json`` entry, its fine doctrine slug
    narrows the stance attribution and enriches the query.

    Air-gap: cultural store ONLY. Never connects to the lexical store. Fail-soft:
    any missing config or unreachable store yields an empty list, never a raise.
    """
    if k <= 0:
        return []

    normalized_traditions = _normalize_traditions(traditions)

    doctrine_slug: str | None = None
    if question_id:
        question = _load_question(str(question_id))
        if question is not None:
            doctrine_slug = resolve_doctrine_slug(question)

    query = _query_text(doctrine, ref, doctrine_slug)
    if not query:
        return []

    if settings is None:
        try:
            from retrieval.hybrid import RetrievalSettings

            settings = RetrievalSettings()
        except Exception:
            settings = None

    qdrant_url = getattr(settings, "qdrant_cultural_url", "") or ""
    voyage_key = getattr(settings, "voyage_api_key", "") or ""

    # Over-fetch so the tradition spread and the k cap both have headroom; the
    # caller's handler re-applies its own k slice.
    fetch_limit = max(k, k * 3)
    payloads = _dense_search(
        qdrant_url=qdrant_url,
        voyage_key=voyage_key,
        query_text=query,
        traditions=normalized_traditions,
        limit=fetch_limit,
        qdrant_client=qdrant_client,
        voyage_client=voyage_client,
    )

    chunks = [_chunk_from_payload(p, doctrine_slug) for p in payloads]
    return chunks[:k]
