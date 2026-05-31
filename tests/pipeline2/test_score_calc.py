"""Tests for pipeline2.score_calc (v3.1 bands)."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import (
    BROAD_THRESHOLD,
    CANON_WIDE_THRESHOLD,
    PARTIAL_THRESHOLD,
    compute_lexical_breadth,
    compute_variant_stability,
)
from tests.pipeline2._fixtures import minimal_evidence_dict


def _maximal_dict() -> dict[str, Any]:
    """Saturates every breadth signal so the score hits 1.0 -> canon_wide band."""
    d = minimal_evidence_dict()
    d["verdict"]["pan_canonical"] = True
    d["verdict"]["variant_robust"] = True
    d["lexical_evidence"]["anchor_lemmas"] = [
        {
            "strong": f"H{i:04d}",
            "lemma": f"lemma{i}",
            "transliteration": f"t{i}",
            "occurrences_in_canon": 10,
            "in_anchors": True,
        }
        for i in range(1, 9)
    ]
    d["lexical_evidence"]["concordance_traversed"] = [f"H{i:04d}" for i in range(1, 11)]
    d["lexical_evidence"]["cross_refs_invoked"] = [
        {"from": "John.1.1", "to": f"John.1.{i}", "source": "openbible", "votes": 100}
        for i in range(1, 13)
    ]
    d["lexical_evidence"]["complicating_texts"] = [
        {"ref": f"Mark.1.{i}", "addressed": True, "resolution": f"resolved {i}"}
        for i in range(1, 4)
    ]
    return d


def _minimal_breadth_dict() -> dict[str, Any]:
    d = minimal_evidence_dict()
    d["verdict"]["pan_canonical"] = False
    d["verdict"]["variant_robust"] = False
    d["lexical_evidence"]["anchor_lemmas"] = []
    d["lexical_evidence"]["concordance_traversed"] = []
    d["lexical_evidence"]["cross_refs_invoked"] = []
    d["lexical_evidence"]["complicating_texts"] = []
    return d


# ---------------------------------------------------------------------------
# compute_lexical_breadth: band classification
# ---------------------------------------------------------------------------


def test_maximal_is_canon_wide() -> None:
    e = Evidence.model_validate(_maximal_dict())
    assert compute_lexical_breadth(e) == "canon_wide"


def test_minimal_is_thin() -> None:
    e = Evidence.model_validate(_minimal_breadth_dict())
    assert compute_lexical_breadth(e) == "thin"


def test_canon_wide_requires_pan_canonical_gate() -> None:
    """Score >= CANON_WIDE_THRESHOLD but pan_canonical=False degrades to broad."""
    d = _maximal_dict()
    d["verdict"]["pan_canonical"] = False
    e = Evidence.model_validate(d)
    # Without pan_canonical, the underlying score drops by 0.25*0.7 = 0.175,
    # from 1.0 to 0.825. That still clears BROAD_THRESHOLD (0.70).
    assert compute_lexical_breadth(e) == "broad"


def test_partial_band() -> None:
    """Tune signals so score falls in [PARTIAL_THRESHOLD, BROAD_THRESHOLD)."""
    d = _minimal_breadth_dict()
    d["verdict"]["pan_canonical"] = True  # +0.25
    d["verdict"]["variant_robust"] = True  # +0.15
    # complicating empty -> +0.15 from complicating_resolved_factor=1.0
    # Subtotal: 0.55 — that's >= PARTIAL_THRESHOLD (0.50) but < BROAD_THRESHOLD (0.70).
    e = Evidence.model_validate(d)
    breadth = compute_lexical_breadth(e)
    assert breadth == "partial", f"expected partial, got {breadth}"


def test_broad_band() -> None:
    """Tune signals so score falls in [BROAD_THRESHOLD, CANON_WIDE_THRESHOLD)."""
    d = _minimal_breadth_dict()
    d["verdict"]["pan_canonical"] = True  # +0.25
    d["verdict"]["variant_robust"] = True  # +0.15
    d["lexical_evidence"]["anchor_lemmas"] = [
        {
            "strong": f"H{i:04d}",
            "lemma": f"l{i}",
            "transliteration": f"t{i}",
            "occurrences_in_canon": 10,
            "in_anchors": True,
        }
        for i in range(1, 9)
    ]  # +0.20
    # complicating empty -> +0.15
    # Subtotal: 0.75 — clears BROAD but below CANON_WIDE (0.85).
    e = Evidence.model_validate(d)
    assert compute_lexical_breadth(e) == "broad"


def test_thin_band_boundary() -> None:
    """Score strictly below PARTIAL_THRESHOLD is thin."""
    d = _minimal_breadth_dict()
    d["verdict"]["pan_canonical"] = False  # +0.075 (floor 0.3)
    # complicating empty -> +0.15
    # variant_robust=False -> +0.075
    # Subtotal: 0.30 — below PARTIAL (0.50) -> thin.
    e = Evidence.model_validate(d)
    assert compute_lexical_breadth(e) == "thin"


def test_band_thresholds_are_ordered() -> None:
    """Sanity: thresholds form the expected chain."""
    assert 0.0 < PARTIAL_THRESHOLD < BROAD_THRESHOLD < CANON_WIDE_THRESHOLD <= 1.0


# ---------------------------------------------------------------------------
# compute_variant_stability
# ---------------------------------------------------------------------------


def test_variant_stability_not_in_scope_when_ecm_na() -> None:
    d = minimal_evidence_dict()
    d["variants"]["ecm_status"] = "n/a"
    e = Evidence.model_validate(d)
    assert compute_variant_stability(e) == "not_in_scope"


def test_variant_stability_stable_when_robust_and_in_scope() -> None:
    d = minimal_evidence_dict()
    d["variants"]["ecm_status"] = "ecm-published"
    d["verdict"]["variant_robust"] = True
    e = Evidence.model_validate(d)
    assert compute_variant_stability(e) == "stable"


def test_variant_stability_sensitive_when_in_scope_but_not_robust() -> None:
    d = minimal_evidence_dict()
    d["variants"]["ecm_status"] = "ecm-shadow"
    d["verdict"]["variant_robust"] = False
    e = Evidence.model_validate(d)
    assert compute_variant_stability(e) == "sensitive"


def test_variant_stability_ecm_published_not_robust_is_sensitive() -> None:
    d = minimal_evidence_dict()
    d["variants"]["ecm_status"] = "ecm-published"
    d["verdict"]["variant_robust"] = False
    e = Evidence.model_validate(d)
    assert compute_variant_stability(e) == "sensitive"


# ---------------------------------------------------------------------------
# Order invariance — both post-processors read counts and booleans only.
# ---------------------------------------------------------------------------


def test_breadth_order_invariance_anchor_lemmas() -> None:
    d1 = _maximal_dict()
    d2 = deepcopy(d1)
    d2["lexical_evidence"]["anchor_lemmas"] = list(
        reversed(d2["lexical_evidence"]["anchor_lemmas"])
    )
    e1 = Evidence.model_validate(d1)
    e2 = Evidence.model_validate(d2)
    assert compute_lexical_breadth(e1) == compute_lexical_breadth(e2)


def test_breadth_order_invariance_cross_refs() -> None:
    d1 = _maximal_dict()
    d2 = deepcopy(d1)
    d2["lexical_evidence"]["cross_refs_invoked"] = list(
        reversed(d2["lexical_evidence"]["cross_refs_invoked"])
    )
    e1 = Evidence.model_validate(d1)
    e2 = Evidence.model_validate(d2)
    assert compute_lexical_breadth(e1) == compute_lexical_breadth(e2)


def test_breadth_order_invariance_complicating_mixed() -> None:
    """Permuting addressed/unaddressed complicating texts yields the same band."""
    d = _maximal_dict()
    d["lexical_evidence"]["complicating_texts"] = [
        {"ref": "Mark.1.1", "addressed": True, "resolution": "r1"},
        {"ref": "Mark.1.2", "addressed": False, "resolution": "r2"},
        {"ref": "Mark.1.3", "addressed": True, "resolution": "r3"},
    ]
    d2 = deepcopy(d)
    d2["lexical_evidence"]["complicating_texts"] = list(
        reversed(d2["lexical_evidence"]["complicating_texts"])
    )
    e1 = Evidence.model_validate(d)
    e2 = Evidence.model_validate(d2)
    assert compute_lexical_breadth(e1) == compute_lexical_breadth(e2)


def test_breadth_order_invariance_concordance() -> None:
    d1 = _maximal_dict()
    d2 = deepcopy(d1)
    d2["lexical_evidence"]["concordance_traversed"] = list(
        reversed(d2["lexical_evidence"]["concordance_traversed"])
    )
    e1 = Evidence.model_validate(d1)
    e2 = Evidence.model_validate(d2)
    assert compute_lexical_breadth(e1) == compute_lexical_breadth(e2)


def test_variant_stability_order_invariant() -> None:
    """variant_stability reads only ecm_status + variant_robust; lists are irrelevant."""
    d1 = minimal_evidence_dict()
    d1["variants"]["ecm_status"] = "ecm-published"
    d1["verdict"]["variant_robust"] = True
    d1["lexical_evidence"]["anchor_lemmas"] = []
    d2 = deepcopy(d1)
    # Mutate unrelated list ordering — output must not change.
    d1["lexical_evidence"]["concordance_traversed"] = ["H0001", "H0002"]
    d2["lexical_evidence"]["concordance_traversed"] = ["H0002", "H0001"]
    e1 = Evidence.model_validate(d1)
    e2 = Evidence.model_validate(d2)
    assert compute_variant_stability(e1) == compute_variant_stability(e2)


# ---------------------------------------------------------------------------
# Determinism — repeated computation yields the same value.
# ---------------------------------------------------------------------------


def test_breadth_deterministic_across_runs() -> None:
    e = Evidence.model_validate(_maximal_dict())
    digests = set()
    for _ in range(10):
        band = compute_lexical_breadth(e)
        digests.add(
            hashlib.sha256(json.dumps({"band": band}, sort_keys=True).encode()).hexdigest()
        )
    assert len(digests) == 1


def test_stability_deterministic_across_runs() -> None:
    d = minimal_evidence_dict()
    d["variants"]["ecm_status"] = "ecm-published"
    d["verdict"]["variant_robust"] = True
    e = Evidence.model_validate(d)
    digests = set()
    for _ in range(10):
        stab = compute_variant_stability(e)
        digests.add(
            hashlib.sha256(json.dumps({"stab": stab}, sort_keys=True).encode()).hexdigest()
        )
    assert len(digests) == 1


def test_breadth_two_instances_same_band() -> None:
    e1 = Evidence.model_validate(_maximal_dict())
    e2 = Evidence.model_validate(_maximal_dict())
    assert compute_lexical_breadth(e1) == compute_lexical_breadth(e2)


# ---------------------------------------------------------------------------
# pan_canonical gate is exclusive to canon_wide band.
# ---------------------------------------------------------------------------


def test_pan_canonical_alone_does_not_promote_thin_to_canon_wide() -> None:
    """pan_canonical=True must combine with high underlying score to hit canon_wide."""
    d = _minimal_breadth_dict()
    d["verdict"]["pan_canonical"] = True
    # All other signals stay zero. Score climbs to 0.25 (pan) + 0.15 (complicating
    # empty) + 0.075 (variant_robust=False floor) = 0.475. Below PARTIAL.
    e = Evidence.model_validate(d)
    assert compute_lexical_breadth(e) == "thin"
