"""Tests for the Pipeline 4 dispatcher stack (pipeline4/{dispatcher,triangle,persistence,run}.py).

These tests exist to BREAK the stack, not to rubber-stamp it. Coverage:

  - mock dispatch produces a valid attestation_present=false file,
  - the post-processor recomputes evidence_safe_to_publish from the witness
    license stack (a subagent cannot mislabel a non-redistributable witness),
  - triangle compare passes on identical inputs and fails on a confidence delta
    above 0.05 and on a witness_id set mismatch,
  - persistence round-trips and rewrites _non_redistributable.txt,
  - the --validate-existing path.

No em-dashes or en-dashes anywhere.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pipeline4 import run as p4_run
from pipeline4.dispatcher import DispatchError, Pipeline4Dispatcher
from pipeline4.historical_schema import HistoricalAttestation
from pipeline4.persistence import (
    historical_path,
    list_historical_files,
    load_historical,
    persist_historical,
)
from pipeline4.triangle import compare, stateful_dispatch, triangle_test

PROMPT_PATH = Path("docs/phase_prompts/pipeline4_attestation.md")
REAL_QID = "doc-canon-closed"


# --------------------------------------------------------------------------
# Fixtures: payloads
# --------------------------------------------------------------------------


def _absent_payload(question_id: str) -> dict:
    return {
        "$schema_version": "1.0",
        "id": question_id,
        "question_id": question_id,
        "generated_at": "2026-06-04T00:00:00Z",
        "pipeline_version": "v1",
        "model": "mock-stub",
        "attestation_present": False,
        "witnesses": [],
        "summary": "No material extra-biblical witness in v1 sources.",
        "license_audit": {
            "sources_used": [],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": [],
    }


def _dss_witness() -> dict:
    # A CC-BY-NC-4.0 (redistribute=false) DSS witness, Option A transliteration.
    return {
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
            "edition": "ETCBC dss .tf",
        },
        "attestation_type": "parallel",
        "confidence": 0.7,
        "evidence_phrase": "BRWX QWDŠ",
        "rationale": "The scroll preserves a parallel two-spirits framing. Diagnostic only.",
        "contested_interpolation": {
            "type": "none",
            "note": None,
            "redact_for_embedding": False,
        },
        "provenance": {
            "original_language": "hbo",
            "witness_chain": ["qumran-cave-1"],
            "extant_witnesses": ["1QS"],
            "loss_status": "complete",
        },
        "text": "BRWX QWDŠ",
        "text_to_embed": "BRWX QWDŠ",
        "license": "CC-BY-NC-4.0",
        "redistribute": False,
        "license_note": "ETCBC dss CC-BY-NC-4.0.",
    }


def _present_payload(question_id: str, claimed_safe: bool) -> dict:
    w = _dss_witness()
    return {
        "$schema_version": "1.0",
        "id": question_id,
        "question_id": question_id,
        "generated_at": "2026-06-04T00:00:00Z",
        "pipeline_version": "v1",
        "model": "mock-stub",
        "attestation_present": True,
        "witnesses": [w],
        "summary": (
            "The Qumran Community Rule preserves a parallel framing that the "
            "lexical verdict already addresses. The witness corroborates nothing "
            "the verdict denies and complicates nothing the verdict affirms. It is "
            "recorded here as a diagnostic parallel tradition, read on its own "
            "terms, and it does not adjudicate the verdict in any direction at all."
        ),
        "license_audit": {
            "sources_used": [
                {
                    "source_slug": "1qs",
                    "license": "CC-BY-NC-4.0",
                    "redistribute": False,
                }
            ],
            # Subagent CLAIMS this value; the post-processor must override it.
            "evidence_safe_to_publish": claimed_safe,
            "non_redistributable_reason": None if claimed_safe else "DSS NC clause.",
        },
        "flags": ["dss-witness"],
    }


@pytest.fixture
def dispatcher() -> Pipeline4Dispatcher:
    d = Pipeline4Dispatcher.__new__(Pipeline4Dispatcher)
    d.settings = None
    d.prompt_path = PROMPT_PATH
    d._prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    return d


def _patch_bundle(monkeypatch: pytest.MonkeyPatch, qid: str) -> None:
    monkeypatch.setattr(
        "pipeline4.dispatcher.build_historical_context_bundle",
        lambda question_id, settings=None: {
            "phase": "pipeline4_attestation",
            "question_id": qid,
            "question_statement": "",
            "question_metadata": {},
            "lexical_verdict_context": {
                "schema_ref": "docs/EVIDENCE_SCHEMA.md",
                "verdict_summary": {
                    "affirms": None,
                    "lexical_directness": None,
                    "rationale": "",
                },
                "scripture_anchors": [],
                "read_only": True,
            },
            "historical_context_bundle": {"candidate_chunks": []},
            "schema_version": "1.0",
        },
    )


# --------------------------------------------------------------------------
# mock dispatch -> valid attestation_present=false
# --------------------------------------------------------------------------


def test_mock_dispatch_absent_is_valid(
    dispatcher: Pipeline4Dispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bundle(monkeypatch, REAL_QID)
    fn = stateful_dispatch([_absent_payload(REAL_QID)])
    att = dispatcher.dispatch_one(REAL_QID, fn)
    assert isinstance(att, HistoricalAttestation)
    assert att.attestation_present is False
    assert att.witnesses == []
    assert att.question_id == REAL_QID
    assert att.license_audit.evidence_safe_to_publish is True


def test_inputs_carry_task_id_and_output_path(
    dispatcher: Pipeline4Dispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bundle(monkeypatch, REAL_QID)
    captured: dict = {}

    def fn(_prompt: str, inputs: dict) -> dict:
        captured.update(inputs)
        return _absent_payload(REAL_QID)

    dispatcher.dispatch_one(REAL_QID, fn)
    assert captured["task_id"].startswith(f"p4-{REAL_QID}-")
    assert captured["output_path"] == f"tmp/pipeline4_attestation/{captured['task_id']}/"
    assert captured["schema_version"] == "1.0"
    assert captured["phase"] == "pipeline4_attestation"


def test_non_dict_payload_raises(
    dispatcher: Pipeline4Dispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bundle(monkeypatch, REAL_QID)
    fn = stateful_dispatch([["not", "a", "dict"]])  # type: ignore[list-item]
    with pytest.raises(DispatchError):
        dispatcher.dispatch_one(REAL_QID, fn)


# --------------------------------------------------------------------------
# post-processor recomputes evidence_safe_to_publish
# --------------------------------------------------------------------------


def test_post_process_overrides_claimed_safe_to_false(
    dispatcher: Pipeline4Dispatcher,
) -> None:
    # Subagent claims a non-redistributable DSS witness is publish-safe; the
    # post-processor must flip it to false and fill a reason.
    att = dispatcher._post_process(_present_payload(REAL_QID, claimed_safe=True))
    assert att.license_audit.evidence_safe_to_publish is False
    assert att.license_audit.non_redistributable_reason
    assert "1qs" in att.license_audit.non_redistributable_reason


def test_post_process_keeps_correct_safe_flag(
    dispatcher: Pipeline4Dispatcher,
) -> None:
    att = dispatcher._post_process(_absent_payload(REAL_QID))
    assert att.license_audit.evidence_safe_to_publish is True
    assert att.license_audit.non_redistributable_reason is None


def test_recompute_method_matches_post_process(
    dispatcher: Pipeline4Dispatcher,
) -> None:
    raw = _present_payload(REAL_QID, claimed_safe=False)
    att = dispatcher._post_process(raw)
    assert att.recompute_evidence_safe_to_publish() is False


# --------------------------------------------------------------------------
# triangle compare
# --------------------------------------------------------------------------


def test_triangle_compare_passes_on_identical(
    dispatcher: Pipeline4Dispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_bundle(monkeypatch, REAL_QID)
    fn = stateful_dispatch(
        [_present_payload(REAL_QID, False), _present_payload(REAL_QID, False)]
    )
    result = triangle_test(REAL_QID, dispatcher, fn)
    assert result.passed, result.reasons


def test_triangle_passes_within_confidence_tolerance(
    dispatcher: Pipeline4Dispatcher,
) -> None:
    a_raw = _present_payload(REAL_QID, False)
    b_raw = copy.deepcopy(a_raw)
    b_raw["witnesses"][0]["confidence"] = 0.74  # delta 0.04, inside 0.05
    a = dispatcher._post_process(a_raw)
    b = dispatcher._post_process(b_raw)
    assert compare(a, b).passed


def test_triangle_fails_on_confidence_delta_above_tolerance(
    dispatcher: Pipeline4Dispatcher,
) -> None:
    a_raw = _present_payload(REAL_QID, False)
    b_raw = copy.deepcopy(a_raw)
    b_raw["witnesses"][0]["confidence"] = 0.6  # delta 0.10, outside 0.05
    a = dispatcher._post_process(a_raw)
    b = dispatcher._post_process(b_raw)
    result = compare(a, b)
    assert not result.passed
    assert any("confidence drift" in r for r in result.reasons)


def test_triangle_fails_on_witness_id_set_mismatch(
    dispatcher: Pipeline4Dispatcher,
) -> None:
    a = dispatcher._post_process(_present_payload(REAL_QID, False))
    b = dispatcher._post_process(_absent_payload(REAL_QID))
    result = compare(a, b)
    assert not result.passed
    assert any("witness_id set mismatch" in r for r in result.reasons)
    assert any("attestation_present mismatch" in r for r in result.reasons)


# --------------------------------------------------------------------------
# persistence round-trip + _non_redistributable.txt
# --------------------------------------------------------------------------


def test_persist_round_trip(tmp_path: Path) -> None:
    att = HistoricalAttestation.model_validate(_absent_payload(REAL_QID))
    path = persist_historical(att, base=tmp_path)
    assert path == historical_path(REAL_QID, base=tmp_path)
    loaded = load_historical(REAL_QID, base=tmp_path)
    assert loaded.question_id == REAL_QID
    assert loaded.attestation_present is False
    assert REAL_QID + ".json" in list_historical_files(base=tmp_path)


def test_persist_writes_non_redistributable_for_unsafe(tmp_path: Path) -> None:
    unsafe = HistoricalAttestation.model_validate(
        _present_payload(REAL_QID, claimed_safe=False)
    )
    persist_historical(unsafe, base=tmp_path)
    nr = tmp_path / "_non_redistributable.txt"
    assert nr.exists()
    assert REAL_QID in nr.read_text(encoding="utf-8").split()


def test_persist_removes_non_redistributable_when_all_safe(tmp_path: Path) -> None:
    # First write an unsafe file to create the list.
    persist_historical(
        HistoricalAttestation.model_validate(
            _present_payload(REAL_QID, claimed_safe=False)
        ),
        base=tmp_path,
    )
    nr = tmp_path / "_non_redistributable.txt"
    assert nr.exists()
    # Overwrite the same question id with a safe (absent) file.
    persist_historical(
        HistoricalAttestation.model_validate(_absent_payload(REAL_QID)),
        base=tmp_path,
    )
    assert not nr.exists()


# --------------------------------------------------------------------------
# --validate-existing
# --------------------------------------------------------------------------


def test_validate_existing_green_on_valid_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "historical"
    base.mkdir()
    att = HistoricalAttestation.model_validate(_absent_payload(REAL_QID))
    (base / f"{REAL_QID}.json").write_text(
        json.dumps(att.model_dump(by_alias=True, mode="json"), indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(p4_run, "HISTORICAL_DIR", base)
    monkeypatch.setattr(
        "pipeline4.persistence.HISTORICAL_DIR", base, raising=False
    )
    # list_historical_files / load_historical default to HISTORICAL_DIR; patch
    # the names that run._validate_existing actually calls.
    monkeypatch.setattr(
        p4_run, "list_historical_files", lambda: [f"{REAL_QID}.json"]
    )
    monkeypatch.setattr(
        p4_run, "load_historical", lambda qid: load_historical(qid, base=base)
    )
    assert p4_run.main(["--validate-existing"]) == 0


def test_validate_existing_red_on_corrupt_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "historical"
    base.mkdir()
    (base / f"{REAL_QID}.json").write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(
        p4_run, "list_historical_files", lambda: [f"{REAL_QID}.json"]
    )
    monkeypatch.setattr(
        p4_run, "load_historical", lambda qid: load_historical(qid, base=base)
    )
    assert p4_run.main(["--validate-existing"]) == 1


# --------------------------------------------------------------------------
# run.main mock end-to-end (single question, isolated dir)
# --------------------------------------------------------------------------


def test_run_main_mock_single(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "historical"
    monkeypatch.setattr(p4_run, "HISTORICAL_DIR", base)
    monkeypatch.setattr("pipeline4.persistence.HISTORICAL_DIR", base, raising=False)
    # persist_historical defaults to the module-level HISTORICAL_DIR; rebind it.
    import pipeline4.persistence as p4_persist

    monkeypatch.setattr(p4_persist, "HISTORICAL_DIR", base)
    rc = p4_run.main(["--question-id", REAL_QID, "--mock"])
    assert rc == 0
    assert (base / f"{REAL_QID}.json").exists()
    loaded = load_historical(REAL_QID, base=base)
    assert loaded.attestation_present is False
