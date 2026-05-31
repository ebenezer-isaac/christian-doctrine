"""Tests for docs/phase_prompts/pipeline4_attestation.md structural contract.

The Pipeline 4 prompt is the verbatim instruction for the historical-attestation
subagent. These tests lock in: the hard constraints, the inputs block, the
output schema reference, the allowed-tool set, the conditional WebSearch
allowlist, the per-source license posture, and the DSS Option A discipline.

No em-dashes or en-dashes in output or file content.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROMPT_PATH = REPO / "docs" / "phase_prompts" / "pipeline4_attestation.md"


@functools.lru_cache(maxsize=1)
def _load_prompt() -> str:
    if not PROMPT_PATH.exists():
        pytest.skip(f"Prompt file not found: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def test_prompt_exists() -> None:
    assert PROMPT_PATH.exists(), f"Pipeline 4 prompt missing: {PROMPT_PATH}"


def test_phase_title_correct() -> None:
    prompt = _load_prompt()
    assert "Pipeline 4 Historical Attestation" in prompt


def test_hard_constraints_section_present() -> None:
    prompt = _load_prompt()
    assert "Hard constraints" in prompt
    assert "historical store" in prompt
    assert "FORBIDDEN" in prompt


def test_lexical_store_forbidden() -> None:
    """Pipeline 4 must NOT read the lexical store; the lexical verdict is read-only context only."""
    prompt = _load_prompt()
    assert "lexical store" in prompt.lower()
    assert "anything touching the lexical store" in prompt.lower() or "forbidden_stores" in prompt or 'allowed_stores: ["historical"]' in prompt


def test_cultural_store_forbidden() -> None:
    prompt = _load_prompt()
    assert "cultural store" in prompt.lower()
    assert "FORBIDDEN" in prompt


def test_lexical_verdict_is_read_only_context() -> None:
    prompt = _load_prompt()
    assert "read-only context" in prompt.lower() or "context-only" in prompt.lower()
    assert "do not modify" in prompt.lower() or "do not modify or contradict" in prompt.lower()


def test_output_path_constrained() -> None:
    prompt = _load_prompt()
    assert "tmp/pipeline4_attestation/" in prompt


def test_no_em_dash_rule_stated() -> None:
    prompt = _load_prompt()
    assert "em-dashes" in prompt.lower() or "em-dash" in prompt.lower()
    assert "U+2014" in prompt or "U+2013" in prompt


def test_inputs_yaml_block_present() -> None:
    prompt = _load_prompt()
    assert "task_id:" in prompt
    assert "phase: pipeline4_attestation" in prompt
    assert "question_id:" in prompt
    assert "lexical_verdict_context:" in prompt
    assert "historical_context_bundle:" in prompt
    assert "candidate_chunks:" in prompt


def test_output_schema_top_level_shape_referenced() -> None:
    prompt = _load_prompt()
    assert "$schema_version" in prompt
    assert '"1.0"' in prompt
    assert "attestation_present" in prompt
    assert "witnesses" in prompt
    assert "license_audit" in prompt


def test_attestation_types_enumerated_in_prompt() -> None:
    prompt = _load_prompt()
    for slug in ("corroborates", "complicates", "neutral", "parallel", "silent-where-expected"):
        assert slug in prompt, f"attestation_type {slug} not enumerated in prompt"


def test_source_types_enumerated_in_prompt() -> None:
    prompt = _load_prompt()
    for slug in ("jewish-historian", "jewish-philosopher", "second-temple-literature",
                  "roman-historian", "jewish-rabbinic", "qumran-sectarian", "qumran-biblical"):
        assert slug in prompt, f"source_type {slug} not enumerated in prompt"


def test_contested_interpolation_types_enumerated() -> None:
    prompt = _load_prompt()
    for slug in ("partial-interpolation", "recension-layer", "text-critical-variant"):
        assert slug in prompt, f"contested_interpolation type {slug} not enumerated"


def test_dss_option_a_discipline_stated() -> None:
    prompt = _load_prompt()
    assert "DSS Option A discipline" in prompt
    assert "transliteration" in prompt.lower()
    assert "no engine-authored" in prompt.lower() or "no engine-authored English gloss" in prompt.lower()


def test_canonical_known_cases_documented() -> None:
    """Testimonium Flavianum, Test12 recension, Tacitus Chrestianos must be specifically called out."""
    prompt = _load_prompt()
    assert "Testimonium Flavianum" in prompt
    assert "Testaments of the Twelve Patriarchs" in prompt
    assert "Chrestianos" in prompt or "Christianos" in prompt


def test_canonical_complications_documented() -> None:
    """Quirinius, Theudas examples must be documented for attestation_type guidance."""
    prompt = _load_prompt()
    assert "Quirinius" in prompt
    assert "Theudas" in prompt


def test_websearch_fallback_section_present() -> None:
    prompt = _load_prompt()
    assert "WebSearch and WebFetch" in prompt
    assert "Perseus" in prompt
    assert "Sefaria" in prompt
    assert "Wikisource" in prompt or "wikisource" in prompt


def test_forbidden_web_sources_listed() -> None:
    """The forbidden web list must mention denominational and confessional sites."""
    prompt = _load_prompt()
    assert "confessional or denominational" in prompt.lower()
    assert "Wikipedia" in prompt


def test_helper_subdispatch_one_level_only() -> None:
    prompt = _load_prompt()
    assert "Helpers do not dispatch further" in prompt or "one level deep" in prompt.lower()


def test_acceptance_criteria_section_present() -> None:
    prompt = _load_prompt()
    assert "Acceptance criteria" in prompt
    assert "extra=\"forbid\"" in prompt or "extra=forbid" in prompt


def test_what_you_do_not_do_section_present() -> None:
    prompt = _load_prompt()
    assert "What you do not do" in prompt
    assert "do not modify" in prompt.lower()


def test_license_posture_table_present() -> None:
    prompt = _load_prompt()
    assert "CC-BY-SA-4.0" in prompt
    assert "CC-BY-NC-4.0" in prompt
    assert "PD" in prompt
    assert "CC-BY" in prompt
    assert "CC0" in prompt


def test_no_em_or_en_dashes() -> None:
    prompt = _load_prompt()
    assert "—" not in prompt, "Em-dash U+2014 present in pipeline4_attestation.md"
    assert "–" not in prompt, "En-dash U+2013 present in pipeline4_attestation.md"


def test_no_personal_decision_booleans() -> None:
    """Same exclusion as Pipeline 2: respondent testimony lives elsewhere."""
    prompt = _load_prompt()
    assert "would_die_for" in prompt
    assert "cult_marker_if_denied" in prompt


def test_low_confidence_review_threshold() -> None:
    prompt = _load_prompt()
    assert "0.60" in prompt or "0.6" in prompt
    assert "low_confidence" in prompt.lower()
