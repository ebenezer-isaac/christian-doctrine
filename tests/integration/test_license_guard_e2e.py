"""License-guard end-to-end. Phase 06 Task 06.06."""

from __future__ import annotations

import json
from pathlib import Path

from cd_mcp.tools.cultural_overlay import CulturalOverlayInput
from cd_mcp.tools.cultural_overlay import handle as cultural_handle
from cd_mcp.tools.evidence_inspect import EvidenceInspectInput
from cd_mcp.tools.evidence_inspect import handle as evidence_inspect_handle
from cd_mcp.tools.license_audit import LicenseAuditInput
from cd_mcp.tools.license_audit import handle as license_audit_handle
from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from tests.pipeline2._fixtures import minimal_evidence_dict


def _materialize_trinity(tmp_path: Path) -> None:
    e = Evidence.model_validate(minimal_evidence_dict())
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    (tmp_path / "doc-trinity.json").write_text(json.dumps(e_dict, indent=2), encoding="utf-8")


def test_evidence_inspect_audit_match(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    inspect = evidence_inspect_handle(
        EvidenceInspectInput(question_id="doc-trinity"), evidence_dir=tmp_path
    )
    audit = license_audit_handle(
        LicenseAuditInput(subject_type="evidence_file", subject_id="doc-trinity"),
        evidence_dir=tmp_path,
    )
    inspect_sources = {s["source"] for s in inspect["license_audit"]["sources_used"]}
    audit_sources = {s["source"] for s in audit["license_audit"]["sources_used"]}
    assert inspect_sources == audit_sources
    inspect_safe = inspect["license_audit"]["response_safe_to_share"]
    audit_safe = audit["license_audit"]["response_safe_to_share"]
    assert inspect_safe == audit_safe


def test_cultural_overlay_public_share_redacts_nc_chunks() -> None:
    long_text = " ".join(["word"] * 500)
    chunks = [
        {
            "tradition": "catholic-magisterial",
            "source": "Vatican.va-CCC",
            "stance": "affirms",
            "text": long_text,
            "license": "©Libreria-Editrice-Vaticana",
            "redistribute": False,
            "source_work_word_count": 200000,
        },
        {
            "tradition": "reformed",
            "source": "opc.org-WCF",
            "stance": "affirms",
            "text": long_text,
            "license": "public_domain",
            "redistribute": True,
        },
    ]
    env = cultural_handle(
        CulturalOverlayInput(doctrine="ecclesiology", k=5, caller_context="public-share"),
        cultural_chunks=chunks,
    )
    for p in env["result"]["passages"]:
        license_ = next(
            (
                s["license"]
                for s in env["license_audit"]["sources_used"]
                if s["source"] == p["source"]
            ),
            "",
        )
        if license_.startswith("©") and p["snippet"] is not None:
            assert len(p["snippet"].split()) <= 100
