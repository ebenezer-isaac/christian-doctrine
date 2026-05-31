"""Tests for docs/ARCHITECTURE.md Pipeline 4 additions.

Verifies that the architecture spec's Pipeline 4 (historical sidecar)
additions are present and internally consistent: the four-pipelines
diagram, the new layer rows (6.7, 6.8, 7.1), the Pipeline 4 walkthrough,
the phase-prompts table row, the dispatch contract update, the license
posture additions, the repo layout additions, and the glossary updates.

No em-dashes or en-dashes in output.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARCH_PATH = REPO / "docs" / "ARCHITECTURE.md"


@functools.lru_cache(maxsize=1)
def _load_arch() -> str:
    if not ARCH_PATH.exists():
        pytest.skip(f"ARCHITECTURE.md not found: {ARCH_PATH}")
    return ARCH_PATH.read_text(encoding="utf-8")


def test_four_pipelines_section_title() -> None:
    arch = _load_arch()
    assert "## The four pipelines" in arch
    assert "## The three pipelines" not in arch


def test_pipeline4_walkthrough_section_present() -> None:
    arch = _load_arch()
    assert "## Pipeline 4 walkthrough" in arch


def test_layer_6_7_historical_sibling_corpus() -> None:
    arch = _load_arch()
    assert "| 6.7 | Historical sibling corpus" in arch
    assert "Josephus" in arch
    assert "Mishnah" in arch


def test_layer_6_8_historical_tagging_present() -> None:
    arch = _load_arch()
    assert "| 6.8 | Historical-attestation tagging" in arch
    assert "attestation_type" in arch


def test_layer_7_1_historical_attestation_engine_present() -> None:
    arch = _load_arch()
    assert "| 7.1 | Historical attestation engine" in arch
    assert "Pipeline 4" in arch


def test_authority_hierarchy_historical_disclaimer() -> None:
    """Historical attestation does NOT appear on the hierarchy."""
    arch = _load_arch()
    assert "Historical attestation does not appear on the hierarchy" in arch


def test_pipeline3_walkthrough_reads_all_three_stores() -> None:
    arch = _load_arch()
    walk = arch.split("## Pipeline 3 walkthrough")[1].split("## Pipeline 4 walkthrough")[0]
    assert "hist_col" in walk
    assert "historical/" in walk
    assert "attestation_present" in walk


def test_phase_prompts_table_has_pipeline4_row() -> None:
    arch = _load_arch()
    assert "Pipeline 4 attestation" in arch
    assert "docs/phase_prompts/pipeline4_attestation.md" in arch


def test_pipeline4_uses_opus() -> None:
    arch = _load_arch()
    table_section = arch.split("Pipeline 4 attestation")[1].split("\n")[0]
    assert "Opus 4.7" in table_section


def test_dispatch_contract_pipeline4_stores() -> None:
    arch = _load_arch()
    assert '"historical"' in arch
    assert 'forbidden_stores' in arch


def test_pipeline2_forbidden_stores_includes_historical() -> None:
    """The updated dispatch contract must extend Pipeline 2's forbidden_stores to include 'historical'."""
    arch = _load_arch()
    snippet_start = arch.find("Pipeline 2 verdict has")
    snippet_end = arch.find(".", snippet_start + 100) if snippet_start >= 0 else -1
    if snippet_start < 0 or snippet_end < 0:
        pytest.fail("Pipeline 2 dispatch contract sentence not found")
    snippet = arch[snippet_start:snippet_end]
    assert '"cultural"' in snippet
    assert '"historical"' in snippet


def test_license_posture_includes_dss_nc() -> None:
    arch = _load_arch()
    assert "ETCBC/dss" in arch
    assert "CC BY-NC 4.0" in arch or "CC-BY-NC-4.0" in arch


def test_license_posture_includes_perseus_sa() -> None:
    arch = _load_arch()
    assert "Josephus Perseus TEI" in arch or "Josephus" in arch
    assert "CC BY-SA 4.0" in arch or "CC-BY-SA-4.0" in arch


def test_license_posture_includes_philo_pseudepigrapha_mishnah_pd() -> None:
    arch = _load_arch()
    assert "Philo Yonge" in arch
    assert "Pseudepigrapha Charles 1913" in arch
    assert "Mishnah Hebrew Torat Emet" in arch


def test_repo_layout_includes_new_dirs() -> None:
    arch = _load_arch()
    layout = arch.split("## Repo layout")[1] if "## Repo layout" in arch else ""
    assert layout, "Repo layout section missing"
    assert "Pipeline 1 historical adapters" in layout, "ingest/historical/ entry missing from repo layout"
    assert "pipeline4/" in layout
    assert "Pipeline 4 output" in layout, "historical/ output dir entry missing from repo layout"
    assert "HISTORICAL_SCHEMA.md" in layout
    assert "historical_data_inventory_catalog.json" in layout


def test_glossary_pipeline4_terms_present() -> None:
    arch = _load_arch()
    glossary = arch.split("## Glossary")[1] if "## Glossary" in arch else ""
    assert glossary, "Glossary section missing"
    required_terms = [
        "Attestation",
        "Contested interpolation",
        "Historical attestation",
        "Historical sidecar",
        "Pipeline 1 / 2 / 3 / 4",
        "Provenance chain",
    ]
    for term in required_terms:
        assert term in glossary, f"Glossary missing term: {term}"


def test_air_gap_section_mentions_disjoint_labels() -> None:
    arch = _load_arch()
    assert "disjoint labels" in arch or "HistoricalSource" in arch


def test_no_em_or_en_dashes_in_new_sections() -> None:
    """Specifically check the Pipeline 4 walkthrough and adjacent additions."""
    arch = _load_arch()
    section_starts = [
        "## Pipeline 4 walkthrough",
        "Historical attestation does not appear",
        "| 6.7 | Historical sibling corpus",
        "| 6.8 | Historical-attestation tagging",
        "| 7.1 | Historical attestation engine",
    ]
    for start in section_starts:
        idx = arch.find(start)
        if idx < 0:
            continue
        end = idx + 2000
        chunk = arch[idx:end]
        assert "—" not in chunk, f"Em-dash near section: {start}"
        assert "–" not in chunk, f"En-dash near section: {start}"


def test_referenced_phase_prompts_exist_on_disk() -> None:
    arch = _load_arch()
    phase_prompt_dir = REPO / "docs" / "phase_prompts"
    for prompt_name in (
        "orchestrator.md",
        "pipeline1_lexical_ingest.md",
        "pipeline1_cultural_scrape.md",
        "cultural_autotag.md",
        "pipeline2_verdict.md",
        "pipeline3_synthesis.md",
        "pipeline4_attestation.md",
        "validation.md",
    ):
        path = phase_prompt_dir / prompt_name
        if prompt_name in arch:
            assert path.exists(), f"ARCHITECTURE.md references {prompt_name} but file is missing"
