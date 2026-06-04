"""Tests for pipeline4.context_builder source-type-balanced candidate retrieval.

These tests exist to BREAK the balancer, not to rubber-stamp it. The fix under
test makes Pipeline 4 candidate retrieval source-type balanced so no single
tradition (DSS holds ~73% of the ~62k hist_col chunks) can crowd out Josephus,
Tacitus, Mishnah, Philo, and the other witnesses by raw volume.

Coverage:

  - balance_candidates caps EACH source_type at PER_TYPE_LIMIT,
  - it dedupes by chunk_id (first occurrence wins),
  - a lopsided input (100 DSS hits, 2 Josephus hits) yields a balanced output
    where DSS is capped and Josephus is fully retained,
  - the keyword-recall path is unioned on top and is NOT subject to the per-type
    cap,
  - the overall cap is honoured,
  - the dense path degrades to empty (no raise) when the voyage key or Qdrant
    URL is absent, when Qdrant is unreachable, and when a single type query
    throws (the other types survive),
  - build_historical_context_bundle returns the exact Inputs-contract shape with
    a balanced candidate_chunks list, mocking Qdrant + Neo4j (no Docker).

No em-dashes or en-dashes anywhere.
"""

from __future__ import annotations

from typing import Any

import pytest

from pipeline4 import context_builder as cb
from pipeline4.context_builder import (
    CANDIDATE_LIMIT,
    PER_TYPE_LIMIT,
    SOURCE_TYPES,
    balance_candidates,
    build_historical_context_bundle,
)


# --------------------------------------------------------------------------
# Helpers: candidate + fake-Qdrant-point factories
# --------------------------------------------------------------------------


def _cand(chunk_id: str, source_type: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "source_type": source_type,
        "source_slug": source_type.split("-")[0],
        "work_id": "w",
        "anchor_id": "a",
        "text": "t",
        "text_to_embed": "t",
        "language": "el",
        "license": "PD",
        "redistribute": True,
        "contested_interpolation_type": "none",
        "provenance_loss_status": "complete",
    }


def _hits(source_type: str, n: int) -> list[dict[str, Any]]:
    return [_cand(f"{source_type}-{i}", source_type) for i in range(n)]


class _FakePoint:
    def __init__(self, payload: dict[str, Any], pid: str) -> None:
        self.payload = payload
        self.id = pid


class _FakeQueryResult:
    def __init__(self, points: list[_FakePoint]) -> None:
        self.points = points


# --------------------------------------------------------------------------
# balance_candidates: per-type cap
# --------------------------------------------------------------------------


def test_balancer_caps_each_source_type_at_per_type_limit() -> None:
    dense_by_type = {st: _hits(st, PER_TYPE_LIMIT + 5) for st in SOURCE_TYPES}
    out = balance_candidates(dense_by_type, keyword=[])
    for st in SOURCE_TYPES:
        count = sum(1 for c in out if c["source_type"] == st)
        assert count <= PER_TYPE_LIMIT, f"{st} exceeded cap: {count}"


def test_balancer_dedupes_by_chunk_id() -> None:
    # Same chunk_id appears in two type buckets and in the keyword path; it must
    # appear exactly once in the output (first occurrence wins).
    shared = _cand("shared-1", "jewish-historian")
    dense_by_type = {
        "jewish-historian": [shared, _cand("jh-2", "jewish-historian")],
        "roman-historian": [dict(shared)],  # same chunk_id, fresh object
    }
    keyword = [dict(shared), _cand("kw-1", "jewish-rabbinic")]
    out = balance_candidates(dense_by_type, keyword=keyword)
    ids = [c["chunk_id"] for c in out]
    assert ids.count("shared-1") == 1
    assert "jh-2" in ids
    assert "kw-1" in ids


def test_balancer_lopsided_dss_capped_josephus_retained() -> None:
    # The headline case: 100 DSS sectarian hits and 2 Josephus hits. DSS must be
    # capped at PER_TYPE_LIMIT; Josephus must survive in full, not be drowned.
    dense_by_type = {
        "qumran-sectarian": _hits("qumran-sectarian", 100),
        "jewish-historian": _hits("jewish-historian", 2),
    }
    out = balance_candidates(dense_by_type, keyword=[])
    dss = [c for c in out if c["source_type"] == "qumran-sectarian"]
    josephus = [c for c in out if c["source_type"] == "jewish-historian"]
    assert len(dss) == PER_TYPE_LIMIT
    assert len(josephus) == 2
    assert {c["chunk_id"] for c in josephus} == {
        "jewish-historian-0",
        "jewish-historian-1",
    }


def test_balancer_keeps_relevance_order_within_type() -> None:
    # The first PER_TYPE_LIMIT (most relevant) hits per type are kept, not a
    # random subset.
    dense_by_type = {"qumran-sectarian": _hits("qumran-sectarian", PER_TYPE_LIMIT + 4)}
    out = balance_candidates(dense_by_type, keyword=[])
    kept_ids = [c["chunk_id"] for c in out]
    assert kept_ids == [f"qumran-sectarian-{i}" for i in range(PER_TYPE_LIMIT)]


def test_balancer_keyword_path_not_subject_to_per_type_cap() -> None:
    # The keyword-recall path is a small entity-match set; it is unioned on top
    # and is NOT capped per type, so it can add more than PER_TYPE_LIMIT of a
    # type that the dense path also returned (deduped, of course).
    dense_by_type = {"jewish-historian": _hits("jewish-historian", PER_TYPE_LIMIT)}
    keyword = [_cand(f"kw-{i}", "jewish-historian") for i in range(PER_TYPE_LIMIT + 3)]
    out = balance_candidates(dense_by_type, keyword=keyword)
    jh = [c for c in out if c["source_type"] == "jewish-historian"]
    # PER_TYPE_LIMIT from dense + (PER_TYPE_LIMIT + 3) distinct from keyword.
    assert len(jh) == PER_TYPE_LIMIT + (PER_TYPE_LIMIT + 3)


def test_balancer_honours_overall_cap() -> None:
    dense_by_type = {st: _hits(st, PER_TYPE_LIMIT) for st in SOURCE_TYPES}
    keyword = [_cand(f"kw-{i}", "jewish-rabbinic") for i in range(200)]
    out = balance_candidates(dense_by_type, keyword=keyword)
    assert len(out) <= CANDIDATE_LIMIT
    assert len(out) == CANDIDATE_LIMIT  # 7*6 dense + keyword fills to the cap


def test_balancer_empty_inputs_yield_empty() -> None:
    assert balance_candidates({}, keyword=[]) == []
    assert balance_candidates({}, keyword=None) == []


def test_balancer_skips_blank_or_missing_chunk_ids() -> None:
    dense_by_type = {
        "jewish-historian": [
            {"chunk_id": "", "source_type": "jewish-historian"},
            {"source_type": "jewish-historian"},  # no chunk_id key
            _cand("good-1", "jewish-historian"),
        ]
    }
    out = balance_candidates(dense_by_type, keyword=[])
    assert [c["chunk_id"] for c in out] == ["good-1"]


def test_balancer_unknown_source_type_also_capped() -> None:
    # A type outside the canonical seven must still be capped, so a mislabelled
    # bucket cannot dominate either.
    dense_by_type = {"mystery-type": _hits("mystery-type", 50)}
    out = balance_candidates(dense_by_type, keyword=[])
    assert len(out) == PER_TYPE_LIMIT


def test_balancer_does_not_mutate_inputs() -> None:
    dense_by_type = {"qumran-sectarian": _hits("qumran-sectarian", 10)}
    keyword = [_cand("kw-1", "jewish-historian")]
    before_dense_len = len(dense_by_type["qumran-sectarian"])
    before_kw_len = len(keyword)
    balance_candidates(dense_by_type, keyword=keyword)
    assert len(dense_by_type["qumran-sectarian"]) == before_dense_len
    assert len(keyword) == before_kw_len


# --------------------------------------------------------------------------
# _dense_candidates_by_type: graceful degradation, no Docker
# --------------------------------------------------------------------------


class _Settings:
    def __init__(self, voyage: str = "", qdrant: str = "") -> None:
        self.voyage_api_key = voyage
        self.qdrant_cultural_url = qdrant


def test_dense_by_type_empty_query_returns_empty() -> None:
    assert cb._dense_candidates_by_type(_Settings("k", "u"), "") == {}


def test_dense_by_type_missing_keys_returns_empty() -> None:
    assert cb._dense_candidates_by_type(_Settings("", ""), "q") == {}
    assert cb._dense_candidates_by_type(_Settings("k", ""), "q") == {}
    assert cb._dense_candidates_by_type(_Settings("", "u"), "q") == {}


def test_dense_by_type_runs_one_filtered_search_per_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mock voyage + qdrant so no Docker / network is touched. Assert: exactly
    # one query_points per source_type, each filtered to that type and limited
    # to PER_TYPE_LIMIT.
    calls: list[dict[str, Any]] = []

    class _FakeVoyageResult:
        embeddings = [[0.1, 0.2, 0.3]]

    class _FakeVoyageClient:
        def __init__(self, api_key: str) -> None:
            pass

        def embed(self, **kwargs: Any) -> Any:
            return _FakeVoyageResult()

    class _FakeQdrant:
        def __init__(self, url: str) -> None:
            pass

        def query_points(self, **kwargs: Any) -> _FakeQueryResult:
            calls.append(kwargs)
            # Pull the filtered source_type back out of the Filter object so we
            # can return type-correct points.
            cond = kwargs["query_filter"].must[0]
            st = cond.match.value
            return _FakeQueryResult(
                [_FakePoint(_cand(f"{st}-{i}", st), f"{st}-{i}") for i in range(2)]
            )

    import sys
    import types

    import qdrant_client

    fake_voyageai = types.SimpleNamespace(Client=_FakeVoyageClient)
    monkeypatch.setitem(sys.modules, "voyageai", fake_voyageai)
    # Patch QdrantClient on the real module so `from qdrant_client.models import
    # ...` (Filter/FieldCondition/MatchValue) still resolves to the real,
    # import-only classes. No Docker, no network.
    monkeypatch.setattr(qdrant_client, "QdrantClient", _FakeQdrant)

    by_type = cb._dense_candidates_by_type(_Settings("k", "u"), "the question")

    assert len(calls) == len(SOURCE_TYPES)
    filtered_types = {c["query_filter"].must[0].match.value for c in calls}
    assert filtered_types == set(SOURCE_TYPES)
    for c in calls:
        assert c["limit"] == PER_TYPE_LIMIT
        assert c["collection_name"] == cb.HIST_COLLECTION
    assert set(by_type) == set(SOURCE_TYPES)
    for st in SOURCE_TYPES:
        assert all(h["source_type"] == st for h in by_type[st])


def test_dense_by_type_one_type_failing_does_not_sink_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeVoyageResult:
        embeddings = [[0.1, 0.2]]

    class _FakeVoyageClient:
        def __init__(self, api_key: str) -> None:
            pass

        def embed(self, **kwargs: Any) -> Any:
            return _FakeVoyageResult()

    class _FakeQdrant:
        def __init__(self, url: str) -> None:
            pass

        def query_points(self, **kwargs: Any) -> _FakeQueryResult:
            st = kwargs["query_filter"].must[0].match.value
            if st == "qumran-sectarian":
                raise RuntimeError("transient qdrant failure for one type")
            return _FakeQueryResult([_FakePoint(_cand(f"{st}-0", st), f"{st}-0")])

    import sys
    import types

    import qdrant_client

    monkeypatch.setitem(
        sys.modules, "voyageai", types.SimpleNamespace(Client=_FakeVoyageClient)
    )
    monkeypatch.setattr(qdrant_client, "QdrantClient", _FakeQdrant)

    by_type = cb._dense_candidates_by_type(_Settings("k", "u"), "q")
    assert "qumran-sectarian" not in by_type
    assert set(by_type) == set(SOURCE_TYPES) - {"qumran-sectarian"}


def test_dense_by_type_embed_failure_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeVoyageClient:
        def __init__(self, api_key: str) -> None:
            pass

        def embed(self, **kwargs: Any) -> Any:
            raise RuntimeError("voyage unreachable")

    import sys
    import types

    import qdrant_client

    monkeypatch.setitem(
        sys.modules, "voyageai", types.SimpleNamespace(Client=_FakeVoyageClient)
    )
    monkeypatch.setattr(qdrant_client, "QdrantClient", object)
    assert cb._dense_candidates_by_type(_Settings("k", "u"), "q") == {}


# --------------------------------------------------------------------------
# build_historical_context_bundle: shape + balanced candidates, no Docker
# --------------------------------------------------------------------------


def test_build_bundle_shape_no_settings_zero_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No reachable stores: graceful degradation to zero candidates, but the full
    # Inputs-contract shape is preserved. The retrieval helpers are mocked empty
    # so the test is hermetic and deterministic whether or not the cultural
    # Docker stack happens to be running in the environment.
    monkeypatch.setattr(cb, "_dense_candidates_by_type", lambda settings, query: {})
    monkeypatch.setattr(cb, "_keyword_candidates", lambda settings, entities: [])
    qid = "doc-canon-closed"
    bundle = build_historical_context_bundle(qid, settings=None)
    assert bundle["phase"] == "pipeline4_attestation"
    assert bundle["question_id"] == qid
    assert "question_statement" in bundle
    assert set(bundle["question_metadata"]) == {
        "category",
        "subcategory",
        "kind",
        "scripture_anchors",
        "brethren_distinctive",
    }
    lvc = bundle["lexical_verdict_context"]
    assert lvc["schema_ref"] == "docs/EVIDENCE_SCHEMA.md"
    assert lvc["read_only"] is True
    assert set(lvc["verdict_summary"]) == {
        "affirms",
        "lexical_directness",
        "rationale",
    }
    assert bundle["historical_context_bundle"]["candidate_chunks"] == []
    assert bundle["schema_version"] == "1.0"


def test_build_bundle_balances_when_dense_is_lopsided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qid = "doc-canon-closed"
    lopsided = {
        "qumran-sectarian": _hits("qumran-sectarian", 100),
        "jewish-historian": _hits("jewish-historian", 2),
    }
    monkeypatch.setattr(
        cb, "_dense_candidates_by_type", lambda settings, query: lopsided
    )
    monkeypatch.setattr(cb, "_keyword_candidates", lambda settings, entities: [])

    bundle = build_historical_context_bundle(qid, settings=_Settings("k", "u"))
    chunks = bundle["historical_context_bundle"]["candidate_chunks"]
    dss = [c for c in chunks if c["source_type"] == "qumran-sectarian"]
    jh = [c for c in chunks if c["source_type"] == "jewish-historian"]
    assert len(dss) == PER_TYPE_LIMIT
    assert len(jh) == 2
