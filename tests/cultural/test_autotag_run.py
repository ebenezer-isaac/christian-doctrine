"""Tests for the cultural autotag Phase 03 runner (ingest/cultural/autotag_run.py).

Deterministic parts only: batch building, tag validation / confidence floor /
tag cap, collection from jsonl, and Qdrant/Neo4j persistence against fakes. The
live 60k run is driven by the orchestrator, not asserted here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ingest.cultural import autotag_run


class _FakePoint:
    def __init__(self, pid: str, chunk_id: str, text: str, tags: Any = None) -> None:
        self.id = pid
        self.payload = {"chunk_id": chunk_id, "text": text, "doctrine_tags": tags or []}


class _FakeQdrant:
    """Minimal scroll + set_payload double for the cult_col collection."""

    def __init__(self, points: list[_FakePoint]) -> None:
        self._points = points
        self.set_payload_calls: list[tuple[str, list[dict[str, Any]]]] = []

    def scroll(
        self, collection_name: str, limit: int, with_payload: bool, with_vectors: bool, offset: Any
    ) -> tuple[list[_FakePoint], Any]:
        start = offset or 0
        page = self._points[start : start + limit]
        next_offset = start + limit if start + limit < len(self._points) else None
        return page, next_offset

    def set_payload(self, collection_name: str, payload: dict[str, Any], points: list[str]) -> None:
        for pid in points:
            self.set_payload_calls.append((pid, payload["doctrine_tags"]))


def _tag(fine: str = "theology-proper", stance: str = "affirms", conf: float = 0.9) -> dict[str, Any]:
    return {
        "doctrine_coarse": "theology-proper",
        "doctrine_fine": fine,
        "stance": stance,
        "confidence": conf,
        "evidence_phrase": "we believe in one God eternally existing in three persons",
    }


# ---------- build_batches ----------


def test_build_batches_writes_chunkid_and_text_only(tmp_path: Path) -> None:
    pts = [_FakePoint(f"u{i}", f"c{i}", f"text {i}") for i in range(5)]
    manifest = autotag_run.build_batches(tmp_path, batch_size=2, client=_FakeQdrant(pts))
    assert manifest["total_chunks"] == 5
    assert manifest["batch_count"] == 3
    first = json.loads((tmp_path / "batch_0000.json").read_text(encoding="utf-8"))
    assert first == [{"chunk_id": "c0", "text": "text 0"}, {"chunk_id": "c1", "text": "text 1"}]
    # no biasing metadata leaked into the batch payload
    assert set(first[0].keys()) == {"chunk_id", "text"}


def test_build_batches_respects_limit(tmp_path: Path) -> None:
    pts = [_FakePoint(f"u{i}", f"c{i}", "t") for i in range(100)]
    manifest = autotag_run.build_batches(tmp_path, batch_size=10, client=_FakeQdrant(pts), limit=25)
    assert manifest["total_chunks"] == 25


# ---------- collect_tags / validation ----------


def test_collect_tags_drops_low_confidence(tmp_path: Path) -> None:
    d = tmp_path / "task1"
    d.mkdir()
    recs = [
        {"chunk_id": "c1", "doctrine_tags": [_tag(conf=0.9), _tag(fine="christology", conf=0.4)]},
        {"chunk_id": "c2", "doctrine_tags": [_tag(conf=0.5)]},  # all below floor -> dropped
    ]
    (d / "tagged_chunks.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs), encoding="utf-8"
    )
    out = autotag_run.collect_tags(tmp_path)
    assert set(out) == {"c1"}
    assert len(out["c1"]) == 1
    assert out["c1"][0]["confidence"] == 0.9


def test_collect_tags_caps_at_five(tmp_path: Path) -> None:
    d = tmp_path / "t"
    d.mkdir()
    tags = [_tag(conf=0.6 + i * 0.01) for i in range(8)]
    (d / "tagged_chunks.jsonl").write_text(
        json.dumps({"chunk_id": "c1", "doctrine_tags": tags}), encoding="utf-8"
    )
    out = autotag_run.collect_tags(tmp_path)
    assert len(out["c1"]) == autotag_run.MAX_TAGS_PER_CHUNK
    # highest-confidence tags survive the cap
    assert out["c1"][0]["confidence"] >= out["c1"][-1]["confidence"]


def test_collect_tags_rejects_malformed_tag(tmp_path: Path) -> None:
    d = tmp_path / "t"
    d.mkdir()
    bad = {"doctrine_fine": "theology-proper"}  # missing required fields
    (d / "tagged_chunks.jsonl").write_text(
        json.dumps({"chunk_id": "c1", "doctrine_tags": [bad, _tag(conf=0.8)]}), encoding="utf-8"
    )
    out = autotag_run.collect_tags(tmp_path)
    assert len(out["c1"]) == 1  # malformed dropped, valid kept


# ---------- persist_qdrant ----------


def test_persist_qdrant_sets_payload_only_for_tagged(tmp_path: Path) -> None:
    pts = [_FakePoint("u0", "c0", "t"), _FakePoint("u1", "c1", "t"), _FakePoint("u2", "c2", "t")]
    fake = _FakeQdrant(pts)
    tags = {"c0": [_tag()], "c2": [_tag(stance="denies")]}
    counts = autotag_run.persist_qdrant(tags, client=fake)
    assert counts == {"scanned": 3, "updated": 2, "chunks_with_tags": 2}
    written = {pid for pid, _ in fake.set_payload_calls}
    assert written == {"u0", "u2"}
    # the persisted payload is the kept tag list (dicts with stance/doctrine_fine)
    payloads = dict(fake.set_payload_calls)
    assert payloads["u2"][0]["stance"] == "denies"
