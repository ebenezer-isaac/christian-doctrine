"""Tests for tools/verify_historical.py static checks.

Hermetic: each test points the verifier at a temp historical dir plus a temp
questions file, so the checks are exercised on controlled fixtures rather than
the live build. Live-store checks (Neo4j, Qdrant) are out of scope here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import verify_historical as vh

PASS = vh.PASS
FAIL = vh.FAIL


def _empty_attestation(qid: str, *, with_dash: bool = False) -> dict:
    summary = "No material extra-biblical witness in v1 sources."
    if with_dash:
        summary = "Contains an em dash — which is forbidden."
    return {
        "$schema_version": "1.0",
        "id": qid,
        "question_id": qid,
        "generated_at": "2026-06-04T00:00:00Z",
        "pipeline_version": "v1",
        "model": "claude-opus-4-8",
        "attestation_present": False,
        "witnesses": [],
        "summary": summary if with_dash else "",
        "license_audit": {
            "sources_used": [],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": [],
    }


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    hist = tmp_path / "historical"
    hist.mkdir()
    questions = tmp_path / "questions.json"

    def write(qids: list[str], *, files: dict[str, dict] | None = None) -> None:
        questions.write_text(
            json.dumps({"questions": [{"id": q} for q in qids]}), encoding="utf-8"
        )
        files = files or {q: _empty_attestation(q) for q in qids}
        for qid, payload in files.items():
            (hist / f"{qid}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )

    monkeypatch.setattr(vh, "HISTORICAL_DIR", hist)
    monkeypatch.setattr(vh, "QUESTIONS", questions)
    return write


def test_clean_build_passes_static_checks(staged) -> None:
    staged(["doc-a", "doc-b", "doc-c"])
    qids = vh._question_ids()
    assert vh.check_coverage(qids).status == PASS
    by_name = {c.name: c for c in vh.check_schema_and_integrity(qids)}
    assert by_name["schema_valid"].status == PASS
    assert by_name["id_equals_question_id"].status == PASS
    assert by_name["evidence_safe_to_publish_derivation"].status == PASS
    assert vh.check_no_dashes().status == PASS


def test_missing_file_fails_coverage(staged) -> None:
    staged(["doc-a", "doc-b"])
    # Add a third question with no corresponding file.
    (vh.QUESTIONS).write_text(
        json.dumps({"questions": [{"id": q} for q in ["doc-a", "doc-b", "doc-missing"]]}),
        encoding="utf-8",
    )
    assert vh.check_coverage(vh._question_ids()).status == FAIL


def test_dash_in_output_fails(staged) -> None:
    staged(["doc-a"], files={"doc-a": _empty_attestation("doc-a", with_dash=True)})
    assert vh.check_no_dashes().status == FAIL


def test_id_mismatch_fails(staged) -> None:
    bad = _empty_attestation("doc-a")
    bad["id"] = "doc-other"
    # An id != question_id payload will not even validate, so it lands in the
    # invalid bucket; either way the schema check must FAIL, not silently pass.
    staged(["doc-a"], files={"doc-a": bad})
    by_name = {c.name: c for c in vh.check_schema_and_integrity(vh._question_ids())}
    assert by_name["schema_valid"].status == FAIL


def test_safe_to_publish_mismatch_fails(staged) -> None:
    # Claim safe-to-publish True while citing a CC-BY-NC (DSS) witness: the
    # recompute must disagree, so the derivation check FAILS.
    payload = {
        "$schema_version": "1.0",
        "id": "doc-a",
        "question_id": "doc-a",
        "generated_at": "2026-06-04T00:00:00Z",
        "pipeline_version": "v1",
        "model": "claude-opus-4-8",
        "attestation_present": True,
        "witnesses": [
            {
                "witness_id": "1qs.col04.line03",
                "source_type": "qumran-sectarian",
                "source": {
                    "source_slug": "1qs",
                    "work_id": "1qs",
                    "work_title": "Community Rule",
                    "author": None,
                    "date_written_range": "c. 100 BCE",
                    "anchor_id": "1qs.col04.line03",
                    "anchor_alt_citation": None,
                    "language": "hbo",
                    "translator": None,
                    "edition": "ETCBC dss",
                },
                "attestation_type": "parallel",
                "confidence": 0.7,
                "evidence_phrase": "transliteration here",
                "rationale": "Scroll attests the dualism.",
                "contested_interpolation": {"type": "none", "note": None, "redact_for_embedding": False},
                "provenance": {
                    "original_language": "hbo",
                    "witness_chain": ["qumran-cave-1"],
                    "extant_witnesses": ["1QS"],
                    "loss_status": "complete",
                },
                "text": "wbyd kwl",
                "text_to_embed": "wbyd kwl",
                "license": "CC-BY-NC-4.0",
                "redistribute": False,
                "license_note": None,
            }
        ],
        "summary": " ".join(["word"] * 60),
        "license_audit": {
            "sources_used": [
                {"source_slug": "1qs", "license": "CC-BY-NC-4.0", "redistribute": False}
            ],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": ["dss-witness"],
    }
    staged(["doc-a"], files={"doc-a": payload})
    by_name = {c.name: c for c in vh.check_schema_and_integrity(vh._question_ids())}
    assert by_name["evidence_safe_to_publish_derivation"].status == FAIL
