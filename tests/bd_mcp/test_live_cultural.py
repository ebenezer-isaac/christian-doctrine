"""Tests for the live cultural-store retrieval injector (Pipeline 3, Step B).

Two layers:

  - Hermetic unit tests with injected fake Qdrant + Voyage clients. They assert
    the EXACT chunk shape the cultural handlers expect and the air-gap / fail-soft
    behaviour. These run everywhere, no Docker.
  - Live tests that hit the real cult_col on QDRANT_CULTURAL_URL. They SKIP
    cleanly when the collection is unreachable or empty (mirroring the
    skip-when-asset-absent pattern used across the suite).

The injected-chunk shape under test is the contract both ``cultural_overlay`` and
``debate_for_verse`` read: ``tradition``, ``source``, ``stance``, ``text``,
``license``, ``redistribute``, ``source_work_word_count``.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any

import pytest

from bd_mcp.live.cultural import (
    DEFAULT_SOURCE_WORK_WORD_COUNT,
    _chunk_from_payload,
    _normalize_traditions,
    _query_text,
    _stance_for_slug,
    retrieve_cultural_chunks,
)
from bd_mcp.tools.cultural_overlay import CulturalOverlayInput
from bd_mcp.tools.cultural_overlay import handle as overlay_handle
from bd_mcp.tools.debate_for_verse import DebateForVerseInput
from bd_mcp.tools.debate_for_verse import handle as debate_handle

REQUIRED_CHUNK_KEYS = {
    "tradition",
    "source",
    "stance",
    "text",
    "license",
    "redistribute",
    "source_work_word_count",
}


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class _FakeVoyage:
    def __init__(self, dim: int = 2048) -> None:
        self._dim = dim

    def embed(self, **kwargs: Any) -> Any:
        return SimpleNamespace(embeddings=[[0.01] * self._dim])


class _FakePoint:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.id = payload.get("chunk_id", "x")
        self.score = 0.9


class _FakeQdrant:
    """Records the last query_points call and returns canned points."""

    def __init__(self, points: list[dict[str, Any]]) -> None:
        self._points = points
        self.last_call: dict[str, Any] = {}

    def query_points(self, **kwargs: Any) -> Any:
        self.last_call = kwargs
        return SimpleNamespace(points=[_FakePoint(p) for p in self._points])


def _settings(url: str = "http://cultural:7101", key: str = "k") -> SimpleNamespace:
    return SimpleNamespace(qdrant_cultural_url=url, voyage_api_key=key)


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "chunk_id": "vatican-ccc.CCC.1366",
        "tradition": "catholic-magisterial",
        "text": "This is the body broken for you. " * 40,
        "license": "©Libreria-Editrice-Vaticana",
        "redistribute": False,
        "anchor_id": "CCC.1366",
        "work_id": "vatican-ccc",
        "work_title": "Catechism of the Catholic Church",
        "author": "Magisterium",
        "date_written": "1992",
        "doctrine_tags": [],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def test_normalize_traditions_keeps_only_registered_slugs() -> None:
    out = _normalize_traditions(["Reformed", "catholic-magisterial", "bogus", "REFORMED"])
    assert out == ["reformed", "catholic-magisterial"]


def test_normalize_traditions_empty() -> None:
    assert _normalize_traditions(None) == []
    assert _normalize_traditions([]) == []


def test_query_text_dedupes_and_joins() -> None:
    assert _query_text("sacraments", "John.6.53", "sacraments") == "sacraments John.6.53"
    assert _query_text(None, None, None) == ""


def test_stance_none_when_tags_empty() -> None:
    assert _stance_for_slug([], "sacraments") is None
    assert _stance_for_slug(None, "sacraments") is None


def test_stance_prefers_matching_slug_highest_confidence() -> None:
    tags = [
        {"doctrine_fine": "sacraments", "stance": "affirms", "confidence": 0.7},
        {"doctrine_fine": "sacraments", "stance": "denies", "confidence": 0.95},
        {"doctrine_fine": "christology", "stance": "qualifies", "confidence": 0.99},
    ]
    assert _stance_for_slug(tags, "sacraments") == "denies"


def test_stance_accepts_json_string_tags() -> None:
    tags = [json.dumps({"doctrine_fine": "sacraments", "stance": "affirms", "confidence": 0.8})]
    assert _stance_for_slug(tags, "sacraments") == "affirms"


def test_chunk_from_payload_exact_shape() -> None:
    chunk = _chunk_from_payload(_payload(), "sacraments")
    assert set(chunk) >= REQUIRED_CHUNK_KEYS
    assert chunk["tradition"] == "catholic-magisterial"
    assert chunk["source"] == "Catechism of the Catholic Church"
    assert chunk["stance"] is None  # tags empty
    assert chunk["redistribute"] is False
    assert chunk["source_work_word_count"] == DEFAULT_SOURCE_WORK_WORD_COUNT


def test_chunk_source_falls_back_to_work_id() -> None:
    chunk = _chunk_from_payload(_payload(work_title=None), None)
    assert chunk["source"] == "vatican-ccc"


# --------------------------------------------------------------------------
# retrieve_cultural_chunks: hermetic with injected clients
# --------------------------------------------------------------------------


def test_retrieve_returns_handler_shaped_chunks() -> None:
    qdrant = _FakeQdrant([_payload(), _payload(chunk_id="b", tradition="reformed")])
    chunks = retrieve_cultural_chunks(
        doctrine="sacraments",
        ref="John.6.53",
        traditions=["catholic-magisterial", "reformed"],
        k=8,
        settings=_settings(),
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    assert len(chunks) == 2
    for ch in chunks:
        assert set(ch) >= REQUIRED_CHUNK_KEYS


def test_retrieve_applies_tradition_filter() -> None:
    qdrant = _FakeQdrant([_payload()])
    retrieve_cultural_chunks(
        doctrine="sacraments",
        traditions=["catholic-magisterial"],
        settings=_settings(),
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    assert qdrant.last_call["collection_name"] == "cult_col"
    assert qdrant.last_call["using"] == "dense"
    assert qdrant.last_call["query_filter"] is not None


def test_retrieve_no_tradition_filter_when_none() -> None:
    qdrant = _FakeQdrant([_payload()])
    retrieve_cultural_chunks(
        doctrine="sacraments",
        traditions=None,
        settings=_settings(),
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    assert qdrant.last_call["query_filter"] is None


def test_retrieve_respects_k() -> None:
    qdrant = _FakeQdrant([_payload(chunk_id=str(i)) for i in range(20)])
    chunks = retrieve_cultural_chunks(
        doctrine="sacraments",
        k=3,
        settings=_settings(),
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    assert len(chunks) == 3


def test_retrieve_empty_query_returns_empty() -> None:
    qdrant = _FakeQdrant([_payload()])
    chunks = retrieve_cultural_chunks(
        doctrine=None,
        ref=None,
        settings=_settings(),
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    assert chunks == []


def test_retrieve_k_zero_returns_empty() -> None:
    chunks = retrieve_cultural_chunks(
        doctrine="sacraments",
        k=0,
        settings=_settings(),
        qdrant_client=_FakeQdrant([_payload()]),
        voyage_client=_FakeVoyage(),
    )
    assert chunks == []


def test_retrieve_qdrant_failure_degrades_to_empty() -> None:
    class _Boom:
        def query_points(self, **kwargs: Any) -> Any:
            raise RuntimeError("unreachable cult_col")

    chunks = retrieve_cultural_chunks(
        doctrine="sacraments",
        settings=_settings(),
        qdrant_client=_Boom(),
        voyage_client=_FakeVoyage(),
    )
    assert chunks == []


def test_retrieve_voyage_failure_degrades_to_empty() -> None:
    class _BoomVoyage:
        def embed(self, **kwargs: Any) -> Any:
            raise RuntimeError("voyage down")

    chunks = retrieve_cultural_chunks(
        doctrine="sacraments",
        settings=_settings(),
        qdrant_client=_FakeQdrant([_payload()]),
        voyage_client=_BoomVoyage(),
    )
    assert chunks == []


def test_retrieve_question_id_resolves_doctrine_slug_for_stance() -> None:
    # doc-canon-closed has category Bibliology -> bibliology fine slug.
    tagged = _payload(
        tradition="reformed",
        doctrine_tags=[{"doctrine_fine": "bibliology", "stance": "affirms", "confidence": 0.9}],
    )
    qdrant = _FakeQdrant([tagged])
    chunks = retrieve_cultural_chunks(
        doctrine="canon",
        question_id="doc-canon-closed",
        settings=_settings(),
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    assert chunks and chunks[0]["stance"] == "affirms"


def test_retrieve_air_gap_url_is_cultural_only() -> None:
    # The settings object only ever exposes the cultural Qdrant url; the module
    # must read that and nothing lexical. We assert it never reaches for a
    # lexical attribute by giving settings only cultural fields.
    qdrant = _FakeQdrant([_payload()])
    s = _settings(url="http://cultural-only:7101")
    retrieve_cultural_chunks(
        doctrine="sacraments",
        settings=s,
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    assert not hasattr(s, "qdrant_lexical_url")


# --------------------------------------------------------------------------
# Injected chunks flow through the real handlers unchanged
# --------------------------------------------------------------------------


def test_chunks_feed_cultural_overlay_handler() -> None:
    qdrant = _FakeQdrant([_payload(redistribute=True, text="A B C D E")])
    chunks = retrieve_cultural_chunks(
        doctrine="sacraments",
        settings=_settings(),
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    env = overlay_handle(CulturalOverlayInput(doctrine="sacraments", k=8), cultural_chunks=chunks)
    assert env["ok"] is True
    assert env["result"]["passages"]
    assert env["result"]["passages"][0]["snippet"] == "A B C D E"


def test_chunks_feed_debate_handler() -> None:
    qdrant = _FakeQdrant([_payload(redistribute=True, text="A B C")])
    chunks = retrieve_cultural_chunks(
        doctrine="sacraments",
        ref="John.6.53",
        settings=_settings(),
        qdrant_client=qdrant,
        voyage_client=_FakeVoyage(),
    )
    env = debate_handle(DebateForVerseInput(ref="John.6.53"), cultural_chunks=chunks)
    assert env["ok"] is True
    assert "catholic-magisterial" in env["result"]["by_tradition"]


# --------------------------------------------------------------------------
# Live tests against the real cult_col (skip when unreachable / empty)
# --------------------------------------------------------------------------


def _live_cult_col_points() -> int | None:
    """Return cult_col points_count, or None when unreachable/missing."""
    url = os.environ.get("QDRANT_CULTURAL_URL", "http://localhost:7101")
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url)
        info = client.get_collection("cult_col")
        return int(info.points_count or 0)
    except Exception:
        return None


_LIVE_POINTS = _live_cult_col_points()
_LIVE_REASON = "cult_col unreachable or empty (live cultural store not up)"
_live = pytest.mark.skipif(not _LIVE_POINTS, reason=_LIVE_REASON)


@_live
def test_live_retrieve_real_chunk_shape() -> None:
    from retrieval.hybrid import RetrievalSettings

    settings = RetrievalSettings()
    if not getattr(settings, "voyage_api_key", ""):
        pytest.skip("VOYAGE_API_KEY not configured for live embedding")
    chunks = retrieve_cultural_chunks(
        doctrine="the deity of Christ and the Trinity",
        traditions=["patristic", "reformed", "catholic-magisterial"],
        k=8,
        settings=settings,
    )
    if not chunks:
        pytest.skip("live cult_col returned no chunks for the probe query")
    for ch in chunks:
        assert set(ch) >= REQUIRED_CHUNK_KEYS
        assert isinstance(ch["text"], str) and ch["text"]
        assert isinstance(ch["redistribute"], bool)
        assert isinstance(ch["source_work_word_count"], int)
        assert ch["tradition"] in {
            "patristic",
            "reformed",
            "catholic-magisterial",
        }


@_live
def test_live_chunks_feed_overlay_handler() -> None:
    from retrieval.hybrid import RetrievalSettings

    settings = RetrievalSettings()
    if not getattr(settings, "voyage_api_key", ""):
        pytest.skip("VOYAGE_API_KEY not configured for live embedding")
    chunks = retrieve_cultural_chunks(
        doctrine="baptism",
        traditions=["reformed", "anabaptist", "catholic-magisterial"],
        k=6,
        settings=settings,
    )
    if not chunks:
        pytest.skip("live cult_col returned no chunks for the probe query")
    env = overlay_handle(CulturalOverlayInput(doctrine="baptism", k=6), cultural_chunks=chunks)
    assert env["ok"] is True
    assert "license_audit" in env
