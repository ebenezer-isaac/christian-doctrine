"""Em-dash and en-dash compliance test for the historical-layer doc set.

The user's standing feedback rule forbids em-dash (U+2014) and en-dash
(U+2013) in any output, including docs, prompts, and catalogs. This test
catches a regression early by sweeping all files added or modified for
Pipeline 4 and asserting absence.

Existing files outside the historical-layer scope are NOT swept because
their compliance is a separate concern owned by other tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

NEW_FILES = (
    "docs/HISTORICAL_SCHEMA.md",
    "docs/historical_data_inventory_catalog.json",
    "docs/phase_prompts/pipeline4_attestation.md",
)

EM_DASH = "—"
EN_DASH = "–"


@pytest.mark.parametrize("rel_path", NEW_FILES)
def test_no_em_dash(rel_path: str) -> None:
    p = REPO / rel_path
    if not p.exists():
        pytest.skip(f"File not found: {p}")
    text = p.read_text(encoding="utf-8")
    if EM_DASH in text:
        line_num = next(
            (i + 1 for i, line in enumerate(text.splitlines()) if EM_DASH in line),
            None,
        )
        pytest.fail(f"Em-dash U+2014 found in {rel_path} at line {line_num}")


@pytest.mark.parametrize("rel_path", NEW_FILES)
def test_no_en_dash(rel_path: str) -> None:
    p = REPO / rel_path
    if not p.exists():
        pytest.skip(f"File not found: {p}")
    text = p.read_text(encoding="utf-8")
    if EN_DASH in text:
        line_num = next(
            (i + 1 for i, line in enumerate(text.splitlines()) if EN_DASH in line),
            None,
        )
        pytest.fail(f"En-dash U+2013 found in {rel_path} at line {line_num}")


def test_no_em_dash_in_architecture_pipeline4_block() -> None:
    """Sweep specifically the Pipeline 4 walkthrough section of ARCHITECTURE.md."""
    arch_path = REPO / "docs" / "ARCHITECTURE.md"
    if not arch_path.exists():
        pytest.skip(f"ARCHITECTURE.md not found: {arch_path}")
    text = arch_path.read_text(encoding="utf-8")
    if "## Pipeline 4 walkthrough" not in text:
        pytest.fail("Pipeline 4 walkthrough section missing from ARCHITECTURE.md")
    section = text.split("## Pipeline 4 walkthrough")[1].split("\n## ")[0]
    assert EM_DASH not in section, "Em-dash in Pipeline 4 walkthrough"
    assert EN_DASH not in section, "En-dash in Pipeline 4 walkthrough"


def test_no_em_dash_in_glossary_additions() -> None:
    arch_path = REPO / "docs" / "ARCHITECTURE.md"
    if not arch_path.exists():
        pytest.skip(f"ARCHITECTURE.md not found: {arch_path}")
    text = arch_path.read_text(encoding="utf-8")
    if "## Glossary" not in text:
        pytest.fail("Glossary section missing")
    glossary = text.split("## Glossary")[1]
    historical_lines = [
        line for line in glossary.splitlines()
        if any(term in line for term in (
            "Attestation",
            "Contested interpolation",
            "Historical attestation",
            "Historical sidecar",
            "Provenance chain",
            "Pipeline 1 / 2 / 3 / 4",
        ))
    ]
    for line in historical_lines:
        assert EM_DASH not in line, f"Em-dash in glossary line: {line!r}"
        assert EN_DASH not in line, f"En-dash in glossary line: {line!r}"
