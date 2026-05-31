"""Tests for pipeline2.context_builder."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pipeline2.context_builder import (
    build_lexical_context_bundle,
    load_question,
    to_osis,
)


def test_to_osis_simple() -> None:
    assert to_osis("John 1:1") == ["John.1.1"]


def test_to_osis_range() -> None:
    assert to_osis("John 1:1-3") == ["John.1.1", "John.1.2", "John.1.3"]


def test_to_osis_first_book() -> None:
    assert to_osis("1 Corinthians 13:4") == ["1Cor.13.4"]


def test_to_osis_unknown_book_empty() -> None:
    assert to_osis("Bogus 1:1") == []


def test_to_osis_malformed_empty() -> None:
    assert to_osis("not a ref") == []


def test_load_question_trinity() -> None:
    q = load_question("doc-trinity")
    assert q["id"] == "doc-trinity"
    assert q["category"] == "Theology Proper"
    assert any("28:19" in r for r in q["scripture_anchors"])


def test_load_question_unknown_raises() -> None:
    with pytest.raises(KeyError):
        load_question("doc-bogus")


class _MockSession:
    def __init__(self, driver: _MockDriver) -> None:
        self._driver = driver

    def __enter__(self) -> _MockSession:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def run(self, *_a: object, **_kw: object) -> list[dict[str, Any]]:
        return self._driver.pop_response()


class _MockDriver:
    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = list(responses)

    def session(self) -> _MockSession:
        return _MockSession(self)

    def pop_response(self) -> list[dict[str, Any]]:
        return self._responses.pop(0) if self._responses else []

    def close(self) -> None:
        return None


def _make_driver_for_trinity() -> _MockDriver:
    anchor_lemmas = [
        {
            "strong": "H3068",
            "lemma": "YHWH",
            "transliteration": "yhwh",
            "occurrences_in_canon": 6828,
            "in_anchors": True,
        },
        {
            "strong": "H0430",
            "lemma": "Elohim",
            "transliteration": "elohim",
            "occurrences_in_canon": 2602,
            "in_anchors": True,
        },
        {
            "strong": "G2316",
            "lemma": "theos",
            "transliteration": "theos",
            "occurrences_in_canon": 1317,
            "in_anchors": True,
        },
        {
            "strong": "G3056",
            "lemma": "logos",
            "transliteration": "logos",
            "occurrences_in_canon": 330,
            "in_anchors": True,
        },
        {
            "strong": "G3962",
            "lemma": "pater",
            "transliteration": "pater",
            "occurrences_in_canon": 415,
            "in_anchors": True,
        },
        {
            "strong": "G4151",
            "lemma": "pneuma",
            "transliteration": "pneuma",
            "occurrences_in_canon": 379,
            "in_anchors": True,
        },
    ]
    anchor_verses = [
        {
            "ref": "Matt.28.19",
            "words": [{"surface": "πατρὸς", "strong": "G3962", "morphology": []}],
            "syntactic_role": "",
        }
    ]
    cross_refs = [
        {"from_ref": "Deut.6.4", "to_ref": "Mark.13.32", "source": "openbible", "votes": 95}
    ] + [
        {"from_ref": f"Matt.28.{19}", "to_ref": f"John.1.{i}", "source": "openbible", "votes": 50}
        for i in range(1, 12)
    ]
    semantic = [{"strong": "G2962", "lemma": "kyrios", "louw_nida": "12.9", "sdbh": "deity"}]
    return _MockDriver(
        [
            anchor_lemmas,
            anchor_verses,
            cross_refs,
            semantic,
            [],
            [],
        ]
    )


def test_build_bundle_returns_required_keys() -> None:
    driver = _make_driver_for_trinity()
    with patch("pipeline2.context_builder.get_lexical_driver", return_value=driver):
        settings = MagicMock()
        bundle = build_lexical_context_bundle("doc-trinity", settings)
    assert bundle["question_id"] == "doc-trinity"
    assert bundle["schema_version"] == "3.1"
    assert "lexical_context_bundle" in bundle
    inner = bundle["lexical_context_bundle"]
    for k in (
        "anchor_lemmas",
        "anchor_verses",
        "cross_refs",
        "semantic_domain_neighbors",
        "variant_units",
        "syntactic_context",
    ):
        assert k in inner


def test_build_bundle_trinity_includes_expected_strongs() -> None:
    driver = _make_driver_for_trinity()
    with patch("pipeline2.context_builder.get_lexical_driver", return_value=driver):
        settings = MagicMock()
        bundle = build_lexical_context_bundle("doc-trinity", settings)
    strongs = {al["strong"] for al in bundle["lexical_context_bundle"]["anchor_lemmas"]}
    assert {"H3068", "H0430", "G2316", "G3056"}.issubset(strongs)


def test_build_bundle_trinity_includes_complicating_candidate_in_cross_refs() -> None:
    driver = _make_driver_for_trinity()
    with patch("pipeline2.context_builder.get_lexical_driver", return_value=driver):
        settings = MagicMock()
        bundle = build_lexical_context_bundle("doc-trinity", settings)
    cross_refs = bundle["lexical_context_bundle"]["cross_refs"]
    to_refs = {cr["to"] for cr in cross_refs}
    assert "Mark.13.32" in to_refs


def test_build_bundle_preserves_metadata() -> None:
    driver = _make_driver_for_trinity()
    with patch("pipeline2.context_builder.get_lexical_driver", return_value=driver):
        settings = MagicMock()
        bundle = build_lexical_context_bundle("doc-trinity", settings)
    meta = bundle["question_metadata"]
    assert meta["category"] == "Theology Proper"
    assert meta["kind"] == "doctrine"
    assert isinstance(meta["scripture_anchors"], list)


def test_build_bundle_unknown_question_raises() -> None:
    with pytest.raises(KeyError):
        build_lexical_context_bundle("doc-bogus", MagicMock())


@pytest.mark.skipif(
    os.environ.get("BD_RUN_INTEGRATION") != "1",
    reason="integration test requires lexical Neo4j",
)
def test_build_bundle_live_trinity() -> None:
    from ingest.lexical._common import Settings

    settings = Settings()  # type: ignore[call-arg]
    bundle = build_lexical_context_bundle("doc-trinity", settings)
    assert len(bundle["lexical_context_bundle"]["anchor_lemmas"]) > 5
    assert len(bundle["lexical_context_bundle"]["cross_refs"]) > 10
