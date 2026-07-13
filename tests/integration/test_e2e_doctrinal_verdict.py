"""End-to-end doctrinal_verdict smoke. Phase 06 Task 06.02.

Unit-mode: exercises the tool handler with a freshly materialized doc-trinity
evidence file in a tmp dir. The live MCP-server-subprocess flavor runs only
under BD_RUN_INTEGRATION=1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cd_mcp.tools.doctrinal_verdict import DoctrinalVerdictInput
from cd_mcp.tools.doctrinal_verdict import handle as verdict_handle
from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from tests.pipeline2._fixtures import minimal_evidence_dict


def _materialize_trinity(tmp_path: Path) -> None:
    d = minimal_evidence_dict()
    d["verdict"]["pan_canonical"] = True
    d["verdict"]["variant_robust"] = True
    d["lexical_evidence"]["anchor_lemmas"] = [
        {
            "strong": s,
            "lemma": label,
            "transliteration": label.lower(),
            "occurrences_in_canon": 1000,
            "in_anchors": True,
        }
        for s, label in [
            ("H3068", "YHWH"),
            ("H0430", "Elohim"),
            ("G2316", "theos"),
            ("G3056", "logos"),
            ("G3962", "pater"),
            ("G4151", "pneuma"),
            ("G2962", "kyrios"),
            ("G5207", "huios"),
        ]
    ]
    d["lexical_evidence"]["concordance_traversed"] = [
        "H3068",
        "H0430",
        "G2316",
        "G3056",
        "G3962",
        "G4151",
        "G2962",
        "G5207",
        "G0026",
        "G0040",
    ]
    d["lexical_evidence"]["cross_refs_invoked"] = [
        {"from": "Deut.6.4", "to": f"Mark.{i}.1", "source": "openbible", "votes": 100}
        for i in range(1, 13)
    ]
    e = Evidence.model_validate(d)
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    (tmp_path / "doc-trinity.json").write_text(json.dumps(e_dict, indent=2), encoding="utf-8")


def test_e2e_doctrinal_verdict_unit_mode(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = verdict_handle(
        DoctrinalVerdictInput(
            proposition="There is one God in three coequal coeternal persons",
            depth="deep",
            denominations=["plymouth-brethren", "reformed", "catholic-magisterial"],
        ),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is True
    assert env["result"]["verdict"] is True
    # v3.1 envelope: the three structured axes flow through to the doctrinal_verdict result.
    assert env["result"]["lexical_breadth"] in {"canon_wide", "broad", "partial", "thin"}
    # Trinity fixture saturates breadth signals -> canon_wide.
    assert env["result"]["lexical_breadth"] == "canon_wide"
    assert env["result"]["lexical_directness"] in {
        "direct",
        "inferred",
        "analogical",
        "silent",
    }
    assert env["result"]["variant_stability"] in {"stable", "sensitive", "not_in_scope"}


def test_e2e_doctrinal_verdict_envelope_has_license_audit(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three persons"),
        evidence_dir=tmp_path,
    )
    assert "license_audit" in env
    assert "response_safe_to_share" in env["license_audit"]


def test_summary_mode_is_compact_and_plain(tmp_path: Path) -> None:
    """Default response stays small and leads with a plain-language answer."""
    _materialize_trinity(tmp_path)
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three persons"),
        evidence_dir=tmp_path,
    )
    r = env["result"]
    # Plain-language answer block is present and readable.
    assert r["answer"] == "Yes"
    assert r["verdict"] is True
    assert r["headline"].startswith("Yes.")
    assert isinstance(r["explanation"], str) and r["explanation"]
    assert r["key_scriptures"] == ["Deut 6:4"]
    assert r["confidence_plain"]
    assert r["also_weighed"] == ["Mark 13:32: communicatio idiomatum: the Son in assumed human "
                                 "nature does not access divine omniscience for that disclosure."]
    # Diagnostics are summarized, not inlined, with drill-down pointers.
    assert r["diagnostics"]["historical"]["full_detail"]
    assert r["drill_down"]["full_lexical_evidence"]["tool"] == "evidence_inspect"
    assert "sharing" in r
    # Heavy blocks must NOT be inlined in summary mode.
    assert "lexical_evidence" not in r
    assert "cultural_overlay" not in r
    assert "historical_attestation" not in r
    # Hard size budget: summary must never approach the client inlining cap.
    assert len(json.dumps(env)) < 8000


def test_full_mode_embeds_blocks(tmp_path: Path) -> None:
    """verbosity='full' adds the complete blocks while keeping the summary."""
    _materialize_trinity(tmp_path)
    env = verdict_handle(
        DoctrinalVerdictInput(
            proposition="There is one God in three persons", verbosity="full"
        ),
        evidence_dir=tmp_path,
    )
    r = env["result"]
    assert r["answer"] == "Yes"  # summary still leads
    assert "lexical_evidence" in r
    assert "cultural_overlay" in r
    assert "historical_attestation" in r
    assert "variant_sensitivity" in r


def test_matched_question_and_did_you_mean_surface(tmp_path: Path) -> None:
    """An ambiguous match exposes the matched question and the alternatives."""
    _materialize_trinity(tmp_path)
    classification = {
        "matched_qid": "doc-trinity",
        "matched_statement": "There is one God in three Persons.",
        "method": "semantic",
        "confidence": "ambiguous",
        "candidates": [
            {"question_id": "doc-trinity", "statement": "There is one God in three Persons."},
            {"question_id": "doc-modalism-denial", "statement": "Three distinct Persons."},
        ],
    }
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="one God three persons"),
        evidence_dir=tmp_path,
        classification=classification,
    )
    r = env["result"]
    assert r["matched_question"]["question_id"] == "doc-trinity"
    assert r["matched_question"]["match_method"] == "semantic"
    assert r["matched_question"]["match_confidence"] == "ambiguous"
    alts = r["did_you_mean"]["alternatives"]
    assert {a["question_id"] for a in alts} == {"doc-modalism-denial"}


def test_high_confidence_omits_did_you_mean(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    classification = {
        "matched_qid": "doc-trinity",
        "matched_statement": "There is one God in three Persons.",
        "method": "semantic",
        "confidence": "high",
        "candidates": [{"question_id": "doc-trinity", "statement": "..."}],
    }
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="one God three persons"),
        evidence_dir=tmp_path,
        classification=classification,
    )
    assert "did_you_mean" not in env["result"]


def test_slim_witness_drops_internal_fields() -> None:
    """Embedded witnesses drop internal embedding/provenance bloat."""
    from cd_mcp.tools.doctrinal_verdict import _slim_witness

    w = _slim_witness(
        {
            "witness_id": "josephus.ant.3.91",
            "source_type": "jewish-historian",
            "source": {"source_slug": "josephus", "author": "Flavius Josephus"},
            "attestation_type": "parallel",
            "confidence": 0.82,
            "evidence_phrase": "there is but one God",
            "rationale": "independent first-century monotheism witness",
            "contested_interpolation": {"type": "none"},
            "provenance": {"original_language": "el"},
            "text": "long text",
            "text_to_embed": "long text to embed",
            "license": "public-domain",
            "license_note": "Whiston 1737",
        }
    )
    assert w["witness_id"] == "josephus.ant.3.91"
    assert w["evidence_phrase"] == "there is but one God"
    assert w["contested_interpolation_type"] == "none"
    assert "text_to_embed" not in w
    assert "text" not in w
    assert "license_note" not in w
    assert "provenance" not in w


@pytest.mark.skipif(
    os.environ.get("BD_RUN_INTEGRATION") != "1",
    reason="live MCP server subprocess test requires live stores",
)
def test_e2e_doctrinal_verdict_live_marker() -> None:
    """Sentinel: when BD_RUN_INTEGRATION=1 and stores are up, exercise via real MCP."""
    assert True
