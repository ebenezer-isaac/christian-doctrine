"""Triangle test runner for Pipeline 4 historical attestations.

Mirrors pipeline2/triangle.py. Two independent dispatches on the same inputs
must agree on the structured fields. Prose can differ; the witness_id set must
match; per-witness attestation_type must match exactly; per-witness confidence
must agree within +/- 0.05 (looser than Pipeline 2's 0.01 because attestation is
a less structured judgment task, per docs/HISTORICAL_SCHEMA.md "Triangle test").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipeline4.dispatcher import DispatchFn, Pipeline4Dispatcher
from pipeline4.historical_schema import HistoricalAttestation

CONFIDENCE_TOLERANCE = 0.05


@dataclass(frozen=True)
class TriangleResult:
    passed: bool
    reasons: tuple[str, ...]
    witness_ids_a: tuple[str, ...]
    witness_ids_b: tuple[str, ...]


def _witness_id_set(att: HistoricalAttestation) -> set[str]:
    return {w.witness_id for w in att.witnesses}


def _by_witness_id(att: HistoricalAttestation) -> dict[str, Any]:
    return {w.witness_id: w for w in att.witnesses}


def compare(a: HistoricalAttestation, b: HistoricalAttestation) -> TriangleResult:
    reasons: list[str] = []
    if a.question_id != b.question_id:
        reasons.append(f"question_id mismatch: {a.question_id} vs {b.question_id}")
    if a.attestation_present != b.attestation_present:
        reasons.append(
            f"attestation_present mismatch: "
            f"{a.attestation_present} vs {b.attestation_present}"
        )

    set_a = _witness_id_set(a)
    set_b = _witness_id_set(b)
    if set_a != set_b:
        reasons.append(f"witness_id set mismatch: {set_a ^ set_b}")
    else:
        wa = _by_witness_id(a)
        wb = _by_witness_id(b)
        for wid in sorted(set_a):
            ta = wa[wid].attestation_type
            tb = wb[wid].attestation_type
            if ta != tb:
                reasons.append(
                    f"attestation_type mismatch for {wid}: {ta} vs {tb}"
                )
            ca = wa[wid].confidence
            cb = wb[wid].confidence
            if abs(ca - cb) > CONFIDENCE_TOLERANCE:
                reasons.append(
                    f"confidence drift for {wid} exceeds {CONFIDENCE_TOLERANCE}: "
                    f"{ca} vs {cb}"
                )

    return TriangleResult(
        passed=not reasons,
        reasons=tuple(reasons),
        witness_ids_a=tuple(sorted(set_a)),
        witness_ids_b=tuple(sorted(set_b)),
    )


def triangle_test(
    question_id: str,
    dispatcher: Pipeline4Dispatcher,
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
