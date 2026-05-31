"""Triangle test runner for Pipeline 2 verdicts.

Two independent dispatches on the same inputs must agree on the structured
fields. Prose can differ; sets must match; the post-processor bands must
match exactly. The LLM-set directness axis is allowed to drift by at most
one adjacent step (direct -> inferred -> analogical -> silent).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipeline2.dispatcher import DispatchFn, Pipeline2Dispatcher
from pipeline2.evidence_schema import Evidence

DIRECTNESS_ORDER = ("direct", "inferred", "analogical", "silent")


@dataclass(frozen=True)
class TriangleResult:
    passed: bool
    reasons: tuple[str, ...]
    breadth_a: str | None
    breadth_b: str | None


def _anchor_set(evidence: Evidence) -> set[str]:
    return {al.strong for al in evidence.lexical_evidence.anchor_lemmas}


def _concordance_set(evidence: Evidence) -> set[str]:
    return set(evidence.lexical_evidence.concordance_traversed)


def _complicating_ref_set(evidence: Evidence) -> set[str]:
    return {c.ref for c in evidence.lexical_evidence.complicating_texts}


def _directness_distance(a: str, b: str) -> int:
    return abs(DIRECTNESS_ORDER.index(a) - DIRECTNESS_ORDER.index(b))


def compare(a: Evidence, b: Evidence) -> TriangleResult:
    reasons: list[str] = []
    if a.question_id != b.question_id:
        reasons.append(f"question_id mismatch: {a.question_id} vs {b.question_id}")
    if a.verdict.affirms != b.verdict.affirms:
        reasons.append(f"affirms mismatch: {a.verdict.affirms} vs {b.verdict.affirms}")

    if a.verdict.lexical_breadth != b.verdict.lexical_breadth:
        reasons.append(
            f"lexical_breadth mismatch: {a.verdict.lexical_breadth} vs {b.verdict.lexical_breadth}"
        )
    if a.verdict.variant_stability != b.verdict.variant_stability:
        reasons.append(
            f"variant_stability mismatch: "
            f"{a.verdict.variant_stability} vs {b.verdict.variant_stability}"
        )
    if _directness_distance(a.verdict.lexical_directness, b.verdict.lexical_directness) > 1:
        reasons.append(
            f"lexical_directness drift exceeds one step: "
            f"{a.verdict.lexical_directness} vs {b.verdict.lexical_directness}"
        )

    if _anchor_set(a) != _anchor_set(b):
        reasons.append(f"anchor_lemmas set mismatch: {_anchor_set(a) ^ _anchor_set(b)}")
    if _concordance_set(a) != _concordance_set(b):
        reasons.append(
            f"concordance_traversed set mismatch: {_concordance_set(a) ^ _concordance_set(b)}"
        )
    if _complicating_ref_set(a) != _complicating_ref_set(b):
        reasons.append(
            "complicating_texts ref-set mismatch: "
            f"{_complicating_ref_set(a) ^ _complicating_ref_set(b)}"
        )

    return TriangleResult(
        passed=not reasons,
        reasons=tuple(reasons),
        breadth_a=a.verdict.lexical_breadth,
        breadth_b=b.verdict.lexical_breadth,
    )


def triangle_test(
    question_id: str,
    dispatcher: Pipeline2Dispatcher,
    dispatch_fn: DispatchFn,
) -> TriangleResult:
    a = dispatcher.dispatch_one(question_id, dispatch_fn)
    b = dispatcher.dispatch_one(question_id, dispatch_fn)
    return compare(a, b)


def stateful_dispatch(
    payloads: list[dict[str, Any]],
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """Wrap a list of pre-built payloads so the dispatcher consumes one per call."""
    iterator = iter(payloads)

    def fn(_prompt: str, _inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise RuntimeError("stateful_dispatch exhausted") from exc

    return fn
