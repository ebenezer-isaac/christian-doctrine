"""Tests for retrieval.hybrid."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from retrieval.hybrid import HybridRetriever, RetrievalSettings, RetrievedChunk, rrf_fuse


class _MockPoint:
    def __init__(
        self,
        id_: str,
        score: float,
        text: str,
        license: str = "public_domain",
        redistribute: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.id = id_
        self.score = score
        self.payload = {
            "text": text,
            "license": license,
            "redistribute": redistribute,
            **(extra or {}),
        }


class _MockResponse:
    def __init__(self, points: list[_MockPoint]) -> None:
        self.points = points


class _MockQdrant:
    def __init__(self, dense: dict[str, list[_MockPoint]], sparse: dict[str, list[_MockPoint]]):
        self._dense = dense
        self._sparse = sparse
        self.calls: list[dict[str, Any]] = []

    def query_points(self, **kwargs: Any) -> _MockResponse:
        self.calls.append(kwargs)
        using = kwargs["using"]
        col = kwargs["collection_name"]
        if using == "dense":
            return _MockResponse(self._dense.get(col, []))
        return _MockResponse(self._sparse.get(col, []))


class _MockVoyageResult:
    def __init__(self, vec: list[float]) -> None:
        self.embeddings = [vec]


class _MockVoyage:
    def embed(self, **_kwargs: Any) -> _MockVoyageResult:
        return _MockVoyageResult([0.1, 0.2, 0.3])


def _settings() -> RetrievalSettings:
    return RetrievalSettings()


def test_rrf_fuse_simple() -> None:
    dense = [("a", 1.0), ("b", 0.9), ("c", 0.8)]
    sparse = [("c", 1.0), ("b", 0.9), ("d", 0.8)]
    fused = rrf_fuse(dense, sparse, k=60)
    ids = [pid for pid, _ in fused]
    assert ids[0] == "b" or ids[0] == "c"
    assert set(ids) == {"a", "b", "c", "d"}


def test_rrf_fuse_empty_inputs() -> None:
    assert rrf_fuse([], []) == []


def test_rrf_fuse_higher_rank_wins() -> None:
    dense = [("a", 1.0), ("b", 0.5)]
    sparse = [("a", 1.0), ("b", 0.5)]
    fused = rrf_fuse(dense, sparse)
    assert fused[0][0] == "a"


def test_retrieve_returns_top_k() -> None:
    qdrant = _MockQdrant(
        dense={"lex_col": [_MockPoint(f"p{i}", 1.0 - i * 0.1, f"text{i}") for i in range(10)]},
        sparse={"lex_col": [_MockPoint(f"p{i}", 1.0 - i * 0.1, f"text{i}") for i in range(10)]},
    )
    r = HybridRetriever("lexical", _settings(), qdrant_client=qdrant, voyage_client=_MockVoyage())
    out = r.retrieve("query", k=5)
    assert len(out) == 5
    assert all(isinstance(c, RetrievedChunk) for c in out)


def test_each_chunk_has_license_and_redistribute() -> None:
    qdrant = _MockQdrant(
        dense={"lex_col": [_MockPoint("p1", 1.0, "t", license="CC-BY-4.0", redistribute=True)]},
        sparse={"lex_col": []},
    )
    r = HybridRetriever("lexical", _settings(), qdrant_client=qdrant, voyage_client=_MockVoyage())
    out = r.retrieve("query", k=5)
    assert out[0].license == "CC-BY-4.0"
    assert out[0].redistribute is True


def test_lexical_retriever_only_hits_lexical_collection() -> None:
    qdrant = _MockQdrant(
        dense={
            "lex_col": [_MockPoint("p1", 1.0, "lex")],
            "cult_col": [_MockPoint("p2", 1.0, "cul")],
        },
        sparse={"lex_col": []},
    )
    r = HybridRetriever("lexical", _settings(), qdrant_client=qdrant, voyage_client=_MockVoyage())
    out = r.retrieve("q", k=5)
    assert all(c.source_store == "lexical" for c in out)
    assert all("cul" not in c.text for c in out)


def test_cultural_retriever_only_hits_cultural_collection() -> None:
    qdrant = _MockQdrant(
        dense={
            "cult_col": [_MockPoint("p1", 1.0, "cul")],
            "lex_col": [_MockPoint("p2", 1.0, "lex")],
        },
        sparse={"cult_col": []},
    )
    r = HybridRetriever("cultural", _settings(), qdrant_client=qdrant, voyage_client=_MockVoyage())
    out = r.retrieve("q", k=5)
    assert all(c.source_store == "cultural" for c in out)
    assert all("lex" not in c.text for c in out)


def test_no_voyage_client_returns_empty_dense() -> None:
    qdrant = _MockQdrant(dense={"lex_col": []}, sparse={"lex_col": []})
    r = HybridRetriever("lexical", _settings(), qdrant_client=qdrant)
    out = r.retrieve("q", k=5)
    assert out == []


def test_filters_passed_through_to_qdrant() -> None:
    qdrant = _MockQdrant(dense={"lex_col": []}, sparse={"lex_col": []})
    r = HybridRetriever("lexical", _settings(), qdrant_client=qdrant, voyage_client=_MockVoyage())
    filt = {"must": [{"key": "strong", "match": {"value": "G2316"}}]}
    r.retrieve("q", k=5, filters=filt)
    assert qdrant.calls[0]["query_filter"] == filt


def test_extra_forbid_on_retrieved_chunk() -> None:
    with pytest.raises(ValidationError):
        RetrievedChunk.model_validate(
            {
                "id": "x",
                "text": "y",
                "score": 1.0,
                "source_store": "lexical",
                "license": "public_domain",
                "redistribute": True,
                "bogus": True,
            }
        )


def test_expand_graph_calls_neo4j_when_requested() -> None:
    qdrant = _MockQdrant(
        dense={"lex_col": [_MockPoint("p1", 1.0, "t1")]},
        sparse={"lex_col": []},
    )
    neo4j = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = session
    session.run.return_value = [{"id": "p2"}]
    neo4j.session.return_value = session
    r = HybridRetriever(
        "lexical",
        _settings(),
        qdrant_client=qdrant,
        voyage_client=_MockVoyage(),
        neo4j_driver=neo4j,
    )
    out = r.retrieve("q", k=5, expand_graph=True)
    assert any(c.id == "p1" for c in out)
    assert neo4j.session.called
