"""Tests for pipeline2.dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pipeline2.dispatcher import (
    DispatchError,
    Pipeline2Dispatcher,
    load_subagent_payload,
)
from tests.pipeline2._fixtures import minimal_evidence_dict

LEAN_PROMPT = Path("docs/phase_prompts/pipeline2_verdict.md")


def _bundle_for(question_id: str, _settings: Any = None) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_statement": "stmt",
        "question_metadata": {"category": "Theology Proper", "kind": "doctrine"},
        "lexical_context_bundle": {
            "anchor_lemmas": [],
            "anchor_verses": [],
            "cross_refs": [],
            "semantic_domain_neighbors": [],
            "variant_units": [],
            "syntactic_context": [],
        },
        "schema_version": "3.1",
    }


def _dispatcher() -> Pipeline2Dispatcher:
    settings = MagicMock()
    with patch(
        "pipeline2.context_builder.build_lexical_context_bundle",
        side_effect=_bundle_for,
    ):
        return Pipeline2Dispatcher(settings, LEAN_PROMPT)


def test_init_loads_prompt() -> None:
    d = _dispatcher()
    assert "Pipeline 2 Lexical Verdict" in d.prompt_text


def test_init_missing_prompt_raises(tmp_path: Path) -> None:
    settings = MagicMock()
    with pytest.raises(FileNotFoundError):
        Pipeline2Dispatcher(settings, tmp_path / "missing.md")


def test_dispatch_one_validates_and_attaches_bands() -> None:
    d = _dispatcher()

    def fake_dispatch(_prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return minimal_evidence_dict()

    with patch(
        "pipeline2.dispatcher.build_lexical_context_bundle",
        side_effect=_bundle_for,
    ):
        evidence = d.dispatch_one("doc-trinity", fake_dispatch)
    assert evidence.question_id == "doc-trinity"
    # Post-processor must populate the v3.1 bands; LLM-set directness is preserved.
    assert evidence.verdict.lexical_breadth in {"canon_wide", "broad", "partial", "thin"}
    assert evidence.verdict.lexical_directness in {
        "direct",
        "inferred",
        "analogical",
        "silent",
    }
    assert evidence.verdict.variant_stability in {"stable", "sensitive", "not_in_scope"}


def test_dispatch_one_passes_inputs_to_fn() -> None:
    d = _dispatcher()
    captured: dict[str, Any] = {}

    def fake_dispatch(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        captured["prompt"] = prompt
        captured["inputs"] = inputs
        return minimal_evidence_dict()

    with patch(
        "pipeline2.dispatcher.build_lexical_context_bundle",
        side_effect=_bundle_for,
    ):
        d.dispatch_one("doc-trinity", fake_dispatch)
    assert captured["inputs"]["phase"] == "pipeline2_verdict"
    assert captured["inputs"]["question_id"] == "doc-trinity"
    assert captured["inputs"]["task_id"].startswith("p2-doc-trinity-")
    assert "Pipeline 2 Lexical Verdict" in captured["prompt"]


def test_dispatch_one_non_dict_payload_raises() -> None:
    d = _dispatcher()

    def fake_dispatch(_p: str, _i: dict[str, Any]) -> dict[str, Any]:
        return "not a dict"  # type: ignore[return-value]

    with (
        patch(
            "pipeline2.dispatcher.build_lexical_context_bundle",
            side_effect=_bundle_for,
        ),
        pytest.raises(DispatchError, match="not a dict"),
    ):
        d.dispatch_one("doc-trinity", fake_dispatch)


def test_dispatch_one_schema_fail_raises() -> None:
    d = _dispatcher()

    def fake_dispatch(_p: str, _i: dict[str, Any]) -> dict[str, Any]:
        bad = minimal_evidence_dict()
        bad["verdict"]["affirms"] = "maybe"
        return bad

    with (
        patch(
            "pipeline2.dispatcher.build_lexical_context_bundle",
            side_effect=_bundle_for,
        ),
        pytest.raises(Exception, match="affirms"),
    ):
        d.dispatch_one("doc-trinity", fake_dispatch)


def test_dispatch_one_license_audit_inconsistent_rejected() -> None:
    d = _dispatcher()

    def fake_dispatch(_p: str, _i: dict[str, Any]) -> dict[str, Any]:
        bad = minimal_evidence_dict()
        bad["license_audit"] = {
            "sources_used": [
                {"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": True}
            ],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        }
        return bad

    with (
        patch(
            "pipeline2.dispatcher.build_lexical_context_bundle",
            side_effect=_bundle_for,
        ),
        pytest.raises(Exception, match="redistribute"),
    ):
        d.dispatch_one("doc-trinity", fake_dispatch)


def test_dispatch_all_wave_of_5(tmp_path: Path) -> None:
    d = _dispatcher()
    qids = [f"doc-q{i}" for i in range(7)]
    seen: list[str] = []

    def fake_dispatch(_p: str, inputs: dict[str, Any]) -> dict[str, Any]:
        seen.append(inputs["question_id"])
        payload = minimal_evidence_dict()
        payload["id"] = inputs["question_id"]
        payload["question_id"] = inputs["question_id"]
        return payload

    with patch(
        "pipeline2.dispatcher.build_lexical_context_bundle",
        side_effect=_bundle_for,
    ):
        results = d.dispatch_all(fake_dispatch, qids)
    assert len(results) == 7
    assert {r.question_id for r in results} == set(qids)


def test_dispatch_all_empty_returns_empty_list() -> None:
    d = _dispatcher()
    with patch(
        "pipeline2.dispatcher.build_lexical_context_bundle",
        side_effect=_bundle_for,
    ):
        results = d.dispatch_all(lambda _p, _i: {}, [])
    assert results == []


def test_load_subagent_payload_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(DispatchError):
        load_subagent_payload("nonexistent-task")


def test_load_subagent_payload_reads_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    task_id = "p2-test-001"
    out_dir = tmp_path / "tmp" / "pipeline2_verdict" / task_id
    out_dir.mkdir(parents=True)
    payload = {"foo": "bar"}
    (out_dir / "evidence.json").write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_subagent_payload(task_id)
    assert loaded == payload


def test_bands_attached_after_dispatch_overwriting_nulls() -> None:
    """Subagent may emit nulls for the post-processor fields; dispatcher must fill them."""
    d = _dispatcher()

    def fake_dispatch(_p: str, _i: dict[str, Any]) -> dict[str, Any]:
        payload = minimal_evidence_dict()
        payload["verdict"]["lexical_breadth"] = None
        payload["verdict"]["variant_stability"] = None
        return payload

    with patch(
        "pipeline2.dispatcher.build_lexical_context_bundle",
        side_effect=_bundle_for,
    ):
        evidence = d.dispatch_one("doc-trinity", fake_dispatch)
    assert evidence.verdict.lexical_breadth is not None
    assert evidence.verdict.lexical_breadth in {"canon_wide", "broad", "partial", "thin"}
    assert evidence.verdict.variant_stability is not None
    assert evidence.verdict.variant_stability in {"stable", "sensitive", "not_in_scope"}
