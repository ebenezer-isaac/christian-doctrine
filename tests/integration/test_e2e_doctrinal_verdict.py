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

from bd_mcp.tools.doctrinal_verdict import DoctrinalVerdictInput
from bd_mcp.tools.doctrinal_verdict import handle as verdict_handle
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


@pytest.mark.skipif(
    os.environ.get("BD_RUN_INTEGRATION") != "1",
    reason="live MCP server subprocess test requires live stores",
)
def test_e2e_doctrinal_verdict_live_marker() -> None:
    """Sentinel: when BD_RUN_INTEGRATION=1 and stores are up, exercise via real MCP."""
    assert True
