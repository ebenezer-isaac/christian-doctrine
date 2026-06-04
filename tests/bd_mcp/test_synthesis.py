"""Tests for the Pipeline 3 synthesis dispatcher (bd_mcp/synthesis.py).

The dispatcher mirrors pipeline2/dispatcher.py: an injected dispatch_fn is the
bridge, a deterministic mock here. No Agent, no Anthropic SDK, no live store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import bd_mcp.synthesis as syn
from bd_mcp.synthesis import (
    Pipeline3SynthesisDispatcher,
    SynthesisError,
    make_synthesis_fn,
)
from bd_mcp.tools.doctrinal_verdict import DoctrinalVerdictInput
from bd_mcp.tools.doctrinal_verdict import handle as verdict_handle
from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from tests.pipeline2._fixtures import minimal_evidence_dict


def _evidence_dict() -> dict[str, Any]:
    e = Evidence.model_validate(minimal_evidence_dict())
    d = e.model_dump(by_alias=True)
    d["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    d["verdict"]["variant_stability"] = compute_variant_stability(e)
    return d


def _synthesis_input(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": "doc-trinity",
        "proposition": "There is one God in three coequal coeternal persons",
        "depth": "fast",
        "denominations": ["reformed"],
        "caller_context": "personal",
        "evidence": evidence,
        "historical": {"attestation_present": False, "witnesses": [], "summary": ""},
    }


def _faithful_payload(inputs: dict[str, Any]) -> dict[str, Any]:
    """A mock subagent that summarizes without re-deriving the verdict."""
    ef = inputs["retrieved_lexical"]["evidence_files"][0]
    verdict = ef["evidence"]["verdict"]
    return {
        "task_id": inputs["task_id"],
        "phase": "pipeline3_synthesis",
        "mcp_tool_name": "doctrinal_verdict",
        "user_query": inputs["user_query"],
        "lexical_verdict": {
            "summary": "Synthesized from the locked evidence file.",
            "affirms": verdict["affirms"],
            "lexical_breadth": verdict["lexical_breadth"],
            "lexical_directness": verdict["lexical_directness"],
            "variant_stability": verdict["variant_stability"],
            "key_lemmas": [],
            "key_verses": [],
            "source_evidence_files": [f"evidence/{ef['question_id']}.json"],
        },
        "cultural_overlay": {"by_tradition": {}},
        "variant_sensitivity": {},
        "license_audit": {"sources_used": []},
    }


# ---------- input construction ----------


def test_dispatcher_builds_subagent_inputs() -> None:
    captured: dict[str, Any] = {}

    def dispatch(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        captured["prompt"] = prompt
        captured["inputs"] = inputs
        return _faithful_payload(inputs)

    fn = make_synthesis_fn(dispatch)
    fn(_synthesis_input(_evidence_dict()))

    inputs = captured["inputs"]
    assert inputs["phase"] == "pipeline3_synthesis"
    assert inputs["mcp_tool_name"] == "doctrinal_verdict"
    assert inputs["task_id"].startswith("p3-doc-trinity-")
    assert inputs["retrieved_lexical"]["evidence_files"][0]["question_id"] == "doc-trinity"
    assert inputs["retrieved_historical"]["attestation_present"] is False
    assert inputs["license_constraints"]["caller_context"] == "personal"
    assert inputs["output_path"].startswith("tmp/pipeline3_synthesis/p3-doc-trinity-")
    # the canonical phase prompt is loaded verbatim
    assert "query-synthesis subagent" in captured["prompt"]


def test_dispatcher_missing_prompt_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Pipeline3SynthesisDispatcher(lambda _p, _i: {}, prompt_path=tmp_path / "absent.md")


# ---------- cultural injection (decoupled from the live injector) ----------


def test_dispatcher_passes_cultural_chunks_through() -> None:
    chunks = [
        {
            "tradition": "reformed",
            "source": "WCF",
            "stance": "affirms",
            "text": "x",
            "license": "public_domain",
            "redistribute": True,
            "source_work_word_count": 100000,
        }
    ]
    captured: dict[str, Any] = {}

    def dispatch(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        captured["inputs"] = inputs
        return _faithful_payload(inputs)

    fn = make_synthesis_fn(dispatch, cultural_retriever=lambda _si: chunks)
    fn(_synthesis_input(_evidence_dict()))
    assert captured["inputs"]["retrieved_cultural"]["chunks"] == chunks


def test_dispatcher_cultural_failure_degrades_to_empty() -> None:
    def boom(_si: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("cultural store unreachable")

    captured: dict[str, Any] = {}

    def dispatch(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        captured["inputs"] = inputs
        return _faithful_payload(inputs)

    fn = make_synthesis_fn(dispatch, cultural_retriever=boom)
    fn(_synthesis_input(_evidence_dict()))
    # cultural is diagnostic: a retrieval failure degrades, never raises
    assert captured["inputs"]["retrieved_cultural"]["chunks"] == []


# ---------- payload validation ----------


def test_dispatcher_rejects_payload_without_lexical_verdict() -> None:
    fn = make_synthesis_fn(lambda _p, _i: {"phase": "pipeline3_synthesis"})
    with pytest.raises(SynthesisError, match="lexical_verdict"):
        fn(_synthesis_input(_evidence_dict()))


def test_dispatcher_loads_payload_from_disk_when_dispatch_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(syn, "OUTPUT_ROOT", tmp_path)

    def dispatch_writes(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        out_dir = tmp_path / inputs["task_id"]
        out_dir.mkdir(parents=True)
        (out_dir / "response.json").write_text(
            json.dumps(_faithful_payload(inputs)), encoding="utf-8"
        )
        return {}  # orchestrator wrote to disk, returns an empty ack

    fn = make_synthesis_fn(dispatch_writes)
    out = fn(_synthesis_input(_evidence_dict()))
    assert out["lexical_verdict"]["summary"] == "Synthesized from the locked evidence file."


def test_dispatcher_disk_load_missing_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(syn, "OUTPUT_ROOT", tmp_path)
    fn = make_synthesis_fn(lambda _p, _i: {})
    with pytest.raises(SynthesisError, match="did not write"):
        fn(_synthesis_input(_evidence_dict()))


# ---------- end-to-end through doctrinal_verdict.handle ----------


def test_synthesis_fn_drives_doctrinal_verdict_with_fidelity(tmp_path: Path) -> None:
    evidence = _evidence_dict()
    (tmp_path / "doc-trinity.json").write_text(json.dumps(evidence), encoding="utf-8")
    captured: dict[str, Any] = {}

    def dispatch(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        captured["inputs"] = inputs
        return _faithful_payload(inputs)

    fn = make_synthesis_fn(
        dispatch,
        cultural_retriever=lambda _si: [
            {
                "tradition": "reformed",
                "source": "WCF",
                "stance": "affirms",
                "text": "x",
                "license": "public_domain",
                "redistribute": True,
                "source_work_word_count": 100000,
            }
        ],
    )
    hist = tmp_path / "hist"
    hist.mkdir()
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three coequal coeternal persons"),
        synthesis_fn=fn,
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is True
    assert env["result"]["verdict"] == evidence["verdict"]["affirms"]
    assert "historical_attestation" in env["result"]
    # the synthesis subagent received the cultural chunk and the locked evidence
    assert captured["inputs"]["retrieved_cultural"]["chunks"][0]["tradition"] == "reformed"


def test_synthesis_fn_fidelity_violation_is_caught(tmp_path: Path) -> None:
    evidence = _evidence_dict()
    (tmp_path / "doc-trinity.json").write_text(json.dumps(evidence), encoding="utf-8")

    def lying_dispatch(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _faithful_payload(inputs)
        payload["lexical_verdict"]["affirms"] = not evidence["verdict"]["affirms"]
        return payload

    fn = make_synthesis_fn(lying_dispatch)
    hist = tmp_path / "hist"
    hist.mkdir()
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three coequal coeternal persons"),
        synthesis_fn=fn,
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "verdict_fidelity_violation"
