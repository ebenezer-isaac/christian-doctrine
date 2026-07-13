"""Tests for cd_mcp.question_match: semantic + keyword proposition matching.

The semantic path is exercised with an injected index and a fake voyage client
so it is deterministic and needs no network. The keyword path runs against the
real questions.json (offline fallback).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from cd_mcp import question_match as qm

# ---------------------------------------------------------------------------
# Keyword fallback (offline)
# ---------------------------------------------------------------------------

QUESTIONS = [
    {"id": "doc-trinity", "statement": "There is one God eternally existing in three coequal, "
     "coeternal, distinct Persons: Father, Son, and Holy Spirit."},
    {"id": "doc-modalism-denial", "statement": "The Father, Son, and Holy Spirit are three "
     "distinct, coeternal Persons sharing one divine essence."},
    {"id": "cult-mormon-polytheism", "statement": "There is one and only one true God; humans "
     "do not become gods."},
    {"id": "prc-alcohol", "statement": "Alcohol consumption in moderation is a matter of "
     "Christian liberty; drunkenness is sin."},
]


def test_keyword_match_picks_best_overlap() -> None:
    r = qm.classify(
        "There is one God in three coequal coeternal persons", questions=QUESTIONS
    )
    assert r["matched_qid"] == "doc-trinity"
    assert r["method"] == "keyword"
    assert r["candidates"][0]["question_id"] == "doc-trinity"


def test_keyword_no_overlap_returns_none() -> None:
    r = qm.classify("quantum chromodynamics lattice gauge", questions=QUESTIONS)
    assert r["matched_qid"] == ""
    assert r["confidence"] == "none"


def test_keyword_prefers_doctrine_on_near_tie() -> None:
    # "one true God" overlaps both the mormon (cult-) and is near doc-trinity;
    # on a near-tie the doc- question wins.
    r = qm.classify("there is one God", questions=QUESTIONS)
    assert r["matched_qid"].startswith("doc-")


# ---------------------------------------------------------------------------
# Semantic path (injected index + fake voyage client)
# ---------------------------------------------------------------------------


class _FakeEmbed:
    def __init__(self, vec: list[float]) -> None:
        self.embeddings = [vec]


class _FakeVoyage:
    """Returns a fixed query vector regardless of input."""

    def __init__(self, vec: list[float]) -> None:
        self._vec = vec

    def embed(self, **_: Any) -> _FakeEmbed:
        return _FakeEmbed(self._vec)


def _index(rows: list[tuple[str, list[float]]]) -> dict[str, Any]:
    vectors = np.asarray([v for _, v in rows], dtype="float32")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return {
        "ids": [i for i, _ in rows],
        "statements": [f"stmt {i}" for i, _ in rows],
        "unit_vectors": vectors / norms,
    }


def test_semantic_clear_winner_is_high() -> None:
    index = _index([("doc-a", [1.0, 0.0]), ("doc-b", [0.0, 1.0])])
    voyage = _FakeVoyage([1.0, 0.05])  # strongly aligned to doc-a
    r = qm.classify("anything", voyage_client=voyage, index=index, questions=QUESTIONS)
    assert r["method"] == "semantic"
    assert r["matched_qid"] == "doc-a"
    assert r["confidence"] == "high"


def test_semantic_near_tie_prefers_doctrine() -> None:
    # cult-x is marginally closer, but doc-y is within the near band -> doc- wins.
    index = _index([("cult-x", [1.0, 0.02]), ("doc-y", [1.0, 0.0])])
    voyage = _FakeVoyage([1.0, 0.0])
    r = qm.classify("anything", voyage_client=voyage, index=index, questions=QUESTIONS)
    assert r["matched_qid"] == "doc-y"
    assert r["confidence"] == "ambiguous"
    assert {c["question_id"] for c in r["candidates"]} == {"cult-x", "doc-y"}


def test_semantic_falls_back_to_keyword_when_voyage_returns_none() -> None:
    index = _index([("doc-a", [1.0, 0.0])])

    class _DeadVoyage:
        def embed(self, **_: Any) -> Any:
            raise RuntimeError("voyage down")

    r = qm.classify(
        "There is one God in three coequal coeternal persons",
        voyage_client=_DeadVoyage(),
        index=index,
        questions=QUESTIONS,
    )
    assert r["method"] == "keyword"
    assert r["matched_qid"] == "doc-trinity"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
