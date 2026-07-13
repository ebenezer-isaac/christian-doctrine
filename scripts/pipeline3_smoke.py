#!/usr/bin/env python
"""Pipeline 3 end-to-end smoke harness.

Exercises the self-contained ``doctrinal_verdict`` query path against the REAL
``evidence/`` and ``historical/`` directories, proving the three diagnostic
blocks come back side by side: the lexical verdict (authoritative, read verbatim
from ``evidence/<id>.json``), the cultural overlay (diagnostic, retrieved live
from ``cult_col``), and the historical attestation (diagnostic, from the Pipeline
4 sidecar ``historical/<id>.json``). It runs one question WITH historical
attestation (``doc-bodily-resurrection-of-christ``, 5 witnesses) and one WITHOUT
(``doc-adoption``, attestation_present false), and asserts the per-question
invariants: ok, verdict fidelity, both diagnostic blocks present, a coherent
license audit.

The server does NO synthesis and calls NO LLM. ``doctrinal_verdict.handle``
assembles structured data and the calling model reasons over it. Because the
verdict is read straight from the locked evidence file, it cannot drift. This
harness mirrors what the tool's ``register()`` does at runtime: it retrieves the
cultural chunks live via ``cd_mcp.live.cultural.retrieve_cultural_chunks`` and
passes them into ``handle`` alongside the evidence and historical directories.

The cultural retrieval is fail-soft by contract: if the cultural store or the
voyage key is unavailable, the cultural block degrades to empty (it is diagnostic
and never adjudicates the verdict) and the script still proves the lexical and
historical path, printing a clear note.

Run from the repo root::

    PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/pipeline3_smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cd_mcp.live.cultural import retrieve_cultural_chunks  # noqa: E402
from cd_mcp.tools.doctrinal_verdict import DoctrinalVerdictInput  # noqa: E402
from cd_mcp.tools.doctrinal_verdict import handle as verdict_handle  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "evidence"
HISTORICAL_DIR = REPO_ROOT / "historical"

# Two propositions chosen so the keyword classifier in doctrinal_verdict resolves
# them to the intended question ids. The WITH case carries 5 historical witnesses;
# the WITHOUT case is attestation_present false (verified against historical/).
WITH_ATTESTATION = {
    "label": "WITH historical attestation",
    "expected_qid": "doc-bodily-resurrection-of-christ",
    "proposition": (
        "Jesus Christ rose bodily from the dead in the same physical body that was "
        "crucified, now glorified, not merely a spiritual or non-physical resurrection."
    ),
    "denominations": ["plymouth-brethren", "reformed"],
}
WITHOUT_ATTESTATION = {
    "label": "WITHOUT historical attestation",
    "expected_qid": "doc-adoption",
    "proposition": (
        "By adoption, those justified are received into the family of God, granted the "
        "privileges, name, and inheritance of sons through union with Christ and the "
        "indwelling Spirit of adoption."
    ),
    "denominations": ["plymouth-brethren", "reformed"],
}


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _evidence_affirms(qid: str) -> Any:
    """Read the locked verdict.affirms straight from the evidence file."""
    path = EVIDENCE_DIR / f"{qid}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["verdict"]["affirms"]


def _count_cultural_passages_by_tradition(result: dict[str, Any]) -> dict[str, int]:
    overlay = result.get("cultural_overlay") or {}
    by_tradition = overlay.get("by_tradition") or {}
    return {tradition: len(entries) for tradition, entries in by_tradition.items()}


def _retrieve_cultural(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrieve cultural chunks live, exactly as the tool's register() does.

    Fail-soft by contract: a missing voyage key or an unreachable Qdrant yields an
    empty list. We guard the call here too so the lexical and historical path is
    still proven if the cultural store is down.
    """
    try:
        return retrieve_cultural_chunks(
            doctrine=case["proposition"],
            traditions=case.get("denominations"),
            question_id=case["expected_qid"],
            k=8,
        )
    except Exception as exc:  # noqa: BLE001  cultural overlay is diagnostic, degrade to empty
        print(f"  cultural retrieval raised ({type(exc).__name__}); degrading to empty overlay")
        return []


# --------------------------------------------------------------------------- #
# Per-question run + invariant checks                                          #
# --------------------------------------------------------------------------- #


def run_case(case: dict[str, Any]) -> list[str]:
    """Run one doctrinal_verdict query and check invariants. Returns failures."""
    failures: list[str] = []
    label = case["label"]
    print(f"\n{'=' * 72}")
    print(f"CASE: {label}")
    print(f"  proposition: {case['proposition'][:80]}...")

    chunks = _retrieve_cultural(case)

    env = verdict_handle(
        DoctrinalVerdictInput(
            proposition=case["proposition"],
            denominations=case["denominations"],
            depth="deep",
        ),
        evidence_dir=EVIDENCE_DIR,
        historical_dir=HISTORICAL_DIR,
        cultural_chunks=chunks,
    )

    ok = env.get("ok")
    print(f"  ok: {ok}")
    if not ok:
        err = env.get("error") or {}
        print(f"  ERROR: code={err.get('code')} message={err.get('message')}")
        failures.append(f"{label}: envelope ok is False (error {err.get('code')})")
        return failures

    result = env["result"]
    evidence_file_id = result.get("evidence_file_id")
    print(f"  evidence_file_id: {evidence_file_id}")
    if evidence_file_id != case["expected_qid"]:
        failures.append(
            f"{label}: classifier resolved {evidence_file_id!r}, expected {case['expected_qid']!r}"
        )

    # 1. Verdict fidelity: result.verdict must equal evidence.verdict.affirms.
    verdict = result.get("verdict")
    expected_affirms = _evidence_affirms(case["expected_qid"])
    fidelity_ok = verdict == expected_affirms
    print(f"  verdict: {verdict}  (evidence.affirms={expected_affirms})  fidelity_ok={fidelity_ok}")
    print(
        f"  axes: breadth={result.get('lexical_breadth')} "
        f"directness={result.get('lexical_directness')} "
        f"variant_stability={result.get('variant_stability')}"
    )
    if not fidelity_ok:
        failures.append(f"{label}: verdict {verdict!r} != evidence.affirms {expected_affirms!r}")

    # 2. Historical attestation block present and correctly shaped.
    hist = result.get("historical_attestation")
    if hist is None:
        failures.append(f"{label}: historical_attestation block missing")
    else:
        present = hist.get("attestation_present")
        witnesses = hist.get("witnesses") or []
        print(f"  historical: attestation_present={present}  witnesses={len(witnesses)}")
        if case["expected_qid"] == "doc-bodily-resurrection-of-christ":
            if not present:
                failures.append(f"{label}: expected attestation_present True")
            if len(witnesses) != 5:
                failures.append(f"{label}: expected 5 witnesses, got {len(witnesses)}")
        else:
            if present:
                failures.append(f"{label}: expected attestation_present False")
            if witnesses:
                failures.append(f"{label}: expected no witnesses, got {len(witnesses)}")

    # 3. Cultural overlay block present (may be empty if the store is unavailable).
    overlay = result.get("cultural_overlay")
    if overlay is None:
        failures.append(f"{label}: cultural_overlay block missing")
    else:
        by_tradition = _count_cultural_passages_by_tradition(result)
        total_passages = sum(by_tradition.values())
        if total_passages == 0:
            print(
                "  cultural: 0 passages "
                "(NOTE: cultural store / voyage key unavailable or no match; "
                "lexical + historical path still proven)"
            )
        else:
            print(f"  cultural: {total_passages} passage(s) by tradition: {by_tradition}")

    # 4. License audit present and coherent.
    audit = env.get("license_audit") or {}
    safe = audit.get("response_safe_to_share")
    reason = audit.get("non_redistributable_reason")
    n_sources = len(audit.get("sources_used") or [])
    print(f"  license_audit: response_safe_to_share={safe}  sources_used={n_sources}")
    if reason:
        print(f"  license_audit: non_redistributable_reason={reason[:120]}...")
    if "license_audit" not in env:
        failures.append(f"{label}: license_audit block missing")
    if safe is None:
        failures.append(f"{label}: response_safe_to_share is None")

    return failures


def main() -> int:
    print("Pipeline 3 end-to-end smoke harness")
    print(f"  evidence dir:   {EVIDENCE_DIR}")
    print(f"  historical dir: {HISTORICAL_DIR}")

    if not EVIDENCE_DIR.is_dir():
        print(f"FATAL: evidence dir not found: {EVIDENCE_DIR}")
        return 2
    if not HISTORICAL_DIR.is_dir():
        print(f"FATAL: historical dir not found: {HISTORICAL_DIR}")
        return 2

    all_failures: list[str] = []
    all_failures.extend(run_case(WITH_ATTESTATION))
    all_failures.extend(run_case(WITHOUT_ATTESTATION))

    print(f"\n{'=' * 72}")
    if all_failures:
        print(f"SMOKE FAILED: {len(all_failures)} invariant(s) did not hold:")
        for f in all_failures:
            print(f"  - {f}")
        return 1
    print("SMOKE PASSED: all invariants held for both questions.")
    print("  - ok True, verdict fidelity, historical block, cultural block, license audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
