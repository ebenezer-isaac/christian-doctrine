"""Tests for pipeline2.triangle (v3.1)."""

from __future__ import annotations

from copy import deepcopy

from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from pipeline2.triangle import compare
from tests.pipeline2._fixtures import minimal_evidence_dict


def _materialize(payload: dict) -> Evidence:
    """Validate then attach the deterministic post-processed bands, mirroring
    what Pipeline2Dispatcher does after the subagent returns."""
    e = Evidence.model_validate(payload)
    breadth = compute_lexical_breadth(e)
    stability = compute_variant_stability(e)
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = breadth
    e_dict["verdict"]["variant_stability"] = stability
    return Evidence.model_validate(e_dict)


def test_two_identical_outputs_pass() -> None:
    a = _materialize(minimal_evidence_dict())
    b = _materialize(minimal_evidence_dict())
    result = compare(a, b)
    assert result.passed, result.reasons
    assert result.breadth_a == result.breadth_b


def test_different_prose_same_structured_fields_pass() -> None:
    a_payload = minimal_evidence_dict()
    b_payload = minimal_evidence_dict()
    b_payload["verdict"]["rationale"] = "Completely different prose; structured fields match."
    b_payload["lay_summary"] = a_payload["lay_summary"][:-10] + " ending tweak applied here."
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert result.passed, result.reasons


def test_different_affirms_fail() -> None:
    a_payload = minimal_evidence_dict()
    b_payload = minimal_evidence_dict()
    b_payload["verdict"]["affirms"] = False
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert not result.passed
    assert any("affirms mismatch" in r for r in result.reasons)


def test_lexical_breadth_mismatch_fails() -> None:
    """Diverging breadth bands across two materialized evidence files trips compare."""
    a_payload = minimal_evidence_dict()
    b_payload = minimal_evidence_dict()
    # Drive b's breadth signals down so its post-processed band differs.
    b_payload["verdict"]["pan_canonical"] = False
    b_payload["verdict"]["variant_robust"] = False
    b_payload["lexical_evidence"]["anchor_lemmas"] = []
    b_payload["lexical_evidence"]["concordance_traversed"] = []
    b_payload["lexical_evidence"]["cross_refs_invoked"] = []
    b_payload["lexical_evidence"]["complicating_texts"] = []
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    assert a.verdict.lexical_breadth != b.verdict.lexical_breadth, "fixture sanity"
    result = compare(a, b)
    assert not result.passed
    assert any("lexical_breadth mismatch" in r for r in result.reasons)


def test_variant_stability_mismatch_fails() -> None:
    a_payload = minimal_evidence_dict()
    b_payload = minimal_evidence_dict()
    # a stays not_in_scope (ecm_status=n/a per fixture). Flip b into scope.
    b_payload["variants"]["ecm_status"] = "ecm-published"
    b_payload["verdict"]["variant_robust"] = True
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    assert a.verdict.variant_stability != b.verdict.variant_stability
    result = compare(a, b)
    assert not result.passed
    assert any("variant_stability mismatch" in r for r in result.reasons)


def test_lexical_directness_one_step_drift_tolerated() -> None:
    """direct -> inferred is one step on the four-axis chain; compare must pass."""
    a_payload = minimal_evidence_dict()
    b_payload = minimal_evidence_dict()
    a_payload["verdict"]["lexical_directness"] = "direct"
    b_payload["verdict"]["lexical_directness"] = "inferred"
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    # Structured fields otherwise match, so the only signal would be directness;
    # one-step drift is allowed, so the comparison passes.
    assert result.passed, result.reasons


def test_lexical_directness_two_step_drift_rejected() -> None:
    """direct -> analogical is two steps; compare must fail."""
    a_payload = minimal_evidence_dict()
    b_payload = minimal_evidence_dict()
    a_payload["verdict"]["lexical_directness"] = "direct"
    b_payload["verdict"]["lexical_directness"] = "analogical"
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert not result.passed
    assert any("lexical_directness drift exceeds one step" in r for r in result.reasons)


def test_lexical_directness_three_step_drift_rejected() -> None:
    """direct -> silent is the max distance; compare must fail. Silent also flips affirms."""
    a_payload = minimal_evidence_dict()
    b_payload = minimal_evidence_dict()
    a_payload["verdict"]["lexical_directness"] = "direct"
    b_payload["verdict"]["lexical_directness"] = "silent"
    b_payload["verdict"]["affirms"] = None  # silent requires affirms=null
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert not result.passed
    assert any("lexical_directness drift exceeds one step" in r for r in result.reasons)


def test_anchor_lemmas_set_mismatch_fail() -> None:
    a_payload = minimal_evidence_dict()
    b_payload = deepcopy(a_payload)
    b_payload["lexical_evidence"]["anchor_lemmas"][0]["strong"] = "H9999"
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert not result.passed
    assert any("anchor_lemmas set mismatch" in r for r in result.reasons)


def test_anchor_lemmas_permuted_same_set_pass() -> None:
    a_payload = minimal_evidence_dict()
    b_payload = deepcopy(a_payload)
    b_payload["lexical_evidence"]["anchor_lemmas"] = list(
        reversed(b_payload["lexical_evidence"]["anchor_lemmas"])
    )
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert result.passed, result.reasons


def test_concordance_permuted_same_set_pass() -> None:
    a_payload = minimal_evidence_dict()
    b_payload = deepcopy(a_payload)
    b_payload["lexical_evidence"]["concordance_traversed"] = list(
        reversed(b_payload["lexical_evidence"]["concordance_traversed"])
    )
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert result.passed, result.reasons


def test_complicating_texts_ref_set_mismatch_fail() -> None:
    a_payload = minimal_evidence_dict()
    b_payload = deepcopy(a_payload)
    b_payload["lexical_evidence"]["complicating_texts"][0]["ref"] = "Luke.22.42"
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert not result.passed
    assert any("complicating_texts ref-set mismatch" in r for r in result.reasons)


def test_compare_question_id_mismatch_caught() -> None:
    a_payload = minimal_evidence_dict()
    b_payload = minimal_evidence_dict()
    b_payload["id"] = "doc-other"
    b_payload["question_id"] = "doc-other"
    a = _materialize(a_payload)
    b = _materialize(b_payload)
    result = compare(a, b)
    assert not result.passed
    assert any("question_id mismatch" in r for r in result.reasons)


def test_triangle_result_exposes_breadth_pair() -> None:
    """TriangleResult.breadth_a / breadth_b expose post-processed bands."""
    a = _materialize(minimal_evidence_dict())
    b = _materialize(minimal_evidence_dict())
    result = compare(a, b)
    assert result.breadth_a == a.verdict.lexical_breadth
    assert result.breadth_b == b.verdict.lexical_breadth
