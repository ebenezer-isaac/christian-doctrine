"""Final-acceptance triple. Phase 06 Task 06.08.

Three top-level checks for v1 acceptance. The Pipeline-2-coverage check passes
only when ≥ 220 evidence files exist; otherwise it is skipped with a clear note
(real verdicts require the Max-plan orchestrator run that is documented in
docs/implementation_phases/phase_04_pipeline2.md Task 04.09).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bd_mcp.tools.doctrinal_verdict import DoctrinalVerdictInput
from bd_mcp.tools.doctrinal_verdict import handle as verdict_handle
from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from tests.pipeline2._fixtures import minimal_evidence_dict

EVIDENCE_DIR = Path("evidence")


def _materialize_trinity(target: Path) -> None:
    d = minimal_evidence_dict()
    d["verdict"]["pan_canonical"] = True
    d["verdict"]["variant_robust"] = True
    e = Evidence.model_validate(d)
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    target.write_text(json.dumps(e_dict, indent=2), encoding="utf-8")


def test_end_to_end_doctrinal_verdict(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path / "doc-trinity.json")
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three persons"),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is True
    assert env["result"]["verdict"] is True


def test_pipeline2_coverage() -> None:
    files = list(EVIDENCE_DIR.glob("*.json")) if EVIDENCE_DIR.exists() else []
    count = len(files)
    if count < 220:
        pytest.skip(
            f"only {count} evidence files present; full ≥220 run requires Phase 04 Task 04.09 "
            "(Max-plan orchestrator dispatch over 231 questions)"
        )


def test_mcp_acceptance_via_subprocess() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/bd_mcp/test_acceptance.py",
            "-v",
            "--tb=short",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
