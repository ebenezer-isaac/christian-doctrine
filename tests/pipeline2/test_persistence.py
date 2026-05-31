"""Tests for pipeline2.persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline2.evidence_schema import Evidence
from pipeline2.persistence import (
    evidence_path,
    evidence_publish_safe_list,
    list_evidence_files,
    load_evidence,
    persist_evidence,
)
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from tests.pipeline2._fixtures import minimal_evidence_dict


def _build_evidence(question_id: str, *, safe: bool = True) -> Evidence:
    d = minimal_evidence_dict()
    d["id"] = question_id
    d["question_id"] = question_id
    if not safe:
        d["license_audit"] = {
            "sources_used": [
                {"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": False}
            ],
            "evidence_safe_to_publish": False,
            "non_redistributable_reason": "BHSA CC-BY-NC-4.0",
        }
        d["citations"] = [
            {
                "type": "syntax",
                "source": "ETCBC-BHSA",
                "license": "CC-BY-NC-4.0",
                "redistribute": False,
                "ref": "Gen.1.1",
            }
        ]
    e = Evidence.model_validate(d)
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    return Evidence.model_validate(e_dict)


def test_persist_and_load_round_trip(tmp_path: Path) -> None:
    e = _build_evidence("doc-trinity")
    persist_evidence(e, base=tmp_path)
    loaded = load_evidence("doc-trinity", base=tmp_path)
    assert loaded == e


def test_persist_creates_filename_matching_question_id(tmp_path: Path) -> None:
    e = _build_evidence("doc-baptism")
    persist_evidence(e, base=tmp_path)
    assert (tmp_path / "doc-baptism.json").exists()


def test_non_redistributable_list_rewritten(tmp_path: Path) -> None:
    safe1 = _build_evidence("doc-safe-a", safe=True)
    unsafe1 = _build_evidence("doc-unsafe-a", safe=False)
    unsafe2 = _build_evidence("doc-unsafe-b", safe=False)
    persist_evidence(safe1, base=tmp_path)
    persist_evidence(unsafe1, base=tmp_path)
    persist_evidence(unsafe2, base=tmp_path)
    body = (tmp_path / "_non_redistributable.txt").read_text(encoding="utf-8")
    lines = [line for line in body.split("\n") if line]
    assert lines == sorted(["doc-unsafe-a", "doc-unsafe-b"])


def test_non_redistributable_list_unchanged_after_4th_safe_persist(tmp_path: Path) -> None:
    persist_evidence(_build_evidence("doc-unsafe-a", safe=False), base=tmp_path)
    persist_evidence(_build_evidence("doc-unsafe-b", safe=False), base=tmp_path)
    persist_evidence(_build_evidence("doc-safe-a", safe=True), base=tmp_path)
    before = (tmp_path / "_non_redistributable.txt").read_text(encoding="utf-8")
    persist_evidence(_build_evidence("doc-safe-b", safe=True), base=tmp_path)
    after = (tmp_path / "_non_redistributable.txt").read_text(encoding="utf-8")
    assert before == after


def test_non_redistributable_list_shrinks_when_repersisted_safe(tmp_path: Path) -> None:
    persist_evidence(_build_evidence("doc-x", safe=False), base=tmp_path)
    persist_evidence(_build_evidence("doc-y", safe=False), base=tmp_path)
    persist_evidence(_build_evidence("doc-x", safe=True), base=tmp_path)
    body = (tmp_path / "_non_redistributable.txt").read_text(encoding="utf-8")
    lines = [line for line in body.split("\n") if line]
    assert lines == ["doc-y"]


def test_non_redistributable_list_removed_when_all_safe(tmp_path: Path) -> None:
    persist_evidence(_build_evidence("doc-unsafe", safe=False), base=tmp_path)
    assert (tmp_path / "_non_redistributable.txt").exists()
    persist_evidence(_build_evidence("doc-unsafe", safe=True), base=tmp_path)
    assert not (tmp_path / "_non_redistributable.txt").exists()


def test_re_persist_overwrites_cleanly(tmp_path: Path) -> None:
    e1 = _build_evidence("doc-q")
    persist_evidence(e1, base=tmp_path)
    e2_dict = e1.model_dump(by_alias=True)
    e2_dict["verdict"]["rationale"] = "Refined rationale on second pass."
    e2 = Evidence.model_validate(e2_dict)
    persist_evidence(e2, base=tmp_path)
    loaded = load_evidence("doc-q", base=tmp_path)
    assert loaded.verdict.rationale == "Refined rationale on second pass."


def test_list_evidence_files_sorted(tmp_path: Path) -> None:
    persist_evidence(_build_evidence("doc-b"), base=tmp_path)
    persist_evidence(_build_evidence("doc-a"), base=tmp_path)
    persist_evidence(_build_evidence("doc-c"), base=tmp_path)
    files = list_evidence_files(base=tmp_path)
    assert files == ["doc-a.json", "doc-b.json", "doc-c.json"]


def test_publish_safe_list(tmp_path: Path) -> None:
    persist_evidence(_build_evidence("doc-safe-a", safe=True), base=tmp_path)
    persist_evidence(_build_evidence("doc-unsafe", safe=False), base=tmp_path)
    persist_evidence(_build_evidence("doc-safe-b", safe=True), base=tmp_path)
    assert evidence_publish_safe_list(base=tmp_path) == ["doc-safe-a", "doc-safe-b"]


def test_load_evidence_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_evidence("nope", base=tmp_path)


def test_evidence_path_default_uses_evidence_dir() -> None:
    p = evidence_path("doc-trinity")
    assert p == Path("evidence/doc-trinity.json")


def test_list_evidence_files_missing_dir(tmp_path: Path) -> None:
    from pipeline2.persistence import list_evidence_files as _list

    assert _list(base=tmp_path / "nope") == []


def test_publish_safe_list_missing_dir(tmp_path: Path) -> None:
    from pipeline2.persistence import evidence_publish_safe_list as _safe

    assert _safe(base=tmp_path / "nope") == []


def test_corrupted_json_skipped(tmp_path: Path) -> None:
    from pipeline2.persistence import (
        evidence_publish_safe_list as _safe,
    )

    persist_evidence(_build_evidence("doc-ok", safe=True), base=tmp_path)
    (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")
    # decode error must not crash
    assert _safe(base=tmp_path) == ["doc-ok"]
    # _rewrite is triggered by next persist; should also tolerate the broken file
    persist_evidence(_build_evidence("doc-also-ok", safe=False), base=tmp_path)
    listed = (tmp_path / "_non_redistributable.txt").read_text(encoding="utf-8")
    assert "doc-also-ok" in listed


class _CapturingSession:
    def __init__(self, sink: list[dict[str, Any]]) -> None:
        self._sink = sink

    def __enter__(self) -> _CapturingSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def run(self, _cypher: str, **kwargs: Any) -> _CapturingSession:
        self._sink.append(kwargs)
        return self

    def consume(self) -> None:
        return None


class _CapturingDriver:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def session(self) -> _CapturingSession:
        return _CapturingSession(self.calls)


@pytest.mark.parametrize(
    "affirms_value,expected_str",
    [
        (True, "true"),
        (False, "false"),
        (None, "null"),
        ("disputed", "disputed"),
    ],
)
def test_upsert_verdict_node_serializes_affirms(
    tmp_path: Path,
    affirms_value: object,
    expected_str: str,
) -> None:
    from copy import deepcopy as _dc

    d = minimal_evidence_dict()
    d["verdict"]["affirms"] = affirms_value
    e = Evidence.model_validate(d)
    e_dict = _dc(e.model_dump(by_alias=True))
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    e = Evidence.model_validate(e_dict)
    driver = _CapturingDriver()
    persist_evidence(e, lexical_driver=driver, base=tmp_path)  # type: ignore[arg-type]
    assert len(driver.calls) == 1
    assert driver.calls[0]["affirms"] == expected_str
    assert driver.calls[0]["qid"] == e.question_id


def test_consistency_verification_script(tmp_path: Path) -> None:
    """End-to-end check matching the phase-04 verification recipe."""
    persist_evidence(_build_evidence("doc-a", safe=True), base=tmp_path)
    persist_evidence(_build_evidence("doc-b", safe=False), base=tmp_path)
    persist_evidence(_build_evidence("doc-c", safe=False), base=tmp_path)

    unsafe: list[str] = []
    for p in sorted(tmp_path.glob("*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not raw["license_audit"]["evidence_safe_to_publish"]:
            unsafe.append(raw["question_id"])
    unsafe = sorted(unsafe)

    listed_path = tmp_path / "_non_redistributable.txt"
    listed = sorted([line for line in listed_path.read_text(encoding="utf-8").split("\n") if line])
    assert unsafe == listed
