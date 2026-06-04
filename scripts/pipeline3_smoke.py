#!/usr/bin/env python
"""Pipeline 3 end-to-end smoke harness.

Exercises the ``doctrinal_verdict`` query path against the REAL ``evidence/`` and
``historical/`` directories, proving the three diagnostic blocks come back side
by side: the lexical verdict (authoritative), the cultural overlay (diagnostic,
retrieved live from ``cult_col``), and the historical attestation (diagnostic,
from the Pipeline 4 sidecar). It runs one question WITH historical attestation
(``doc-bodily-resurrection-of-christ``, 5 witnesses) and one WITHOUT
(``doc-adoption``, attestation_present false), and asserts the per-question
invariants: ok, verdict fidelity, both diagnostic blocks present, a coherent
license audit.

This is offline-capable and deterministic. There is no programmatic Anthropic
API anywhere. The synthesis subagent (normally an Opus dispatch) is stood in for
by a FAITHFUL local synthesizer that reads the locked evidence, echoes the
verdict axes verbatim (NEVER re-derives), formats the live-retrieved cultural
chunks, and writes the canonical ``tmp/pipeline3_synthesis/<task_id>/response.json``.

The cultural retriever binds to the live ``retrieve_cultural_chunks`` injector. If
the cultural store or the voyage key is unavailable, the cultural block degrades
to empty (it is diagnostic and never adjudicates the verdict) and the script
still proves the lexical and historical path, printing a clear note.

Run from the repo root::

    python scripts/pipeline3_smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bd_mcp.synthesis import make_synthesis_fn  # noqa: E402
from bd_mcp.tools.doctrinal_verdict import (  # noqa: E402
    DoctrinalVerdictInput,
)
from bd_mcp.tools.doctrinal_verdict import handle as verdict_handle  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "evidence"
HISTORICAL_DIR = REPO_ROOT / "historical"
SYNTHESIS_OUTPUT_ROOT = REPO_ROOT / "tmp" / "pipeline3_synthesis"

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
# Cultural retriever adapter: synthesis_input dict -> live retrieve_cultural   #
# --------------------------------------------------------------------------- #


def _live_cultural_retriever(synthesis_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapter binding the synthesis seam to the live cultural injector.

    Takes the synthesis_input dict, pulls the question_id, proposition (used as
    the doctrine query text) and denominations (used as the tradition filter),
    and calls bd_mcp.live.cultural.retrieve_cultural_chunks. The injector is
    fail-soft by contract (a missing voyage key or unreachable Qdrant yields an
    empty list), and the dispatcher wraps this call in its own try/except so a
    raise here only degrades the diagnostic overlay, never the verdict. We guard
    the import too, so an environment without the live module still runs.
    """
    try:
        from bd_mcp.live.cultural import retrieve_cultural_chunks
    except Exception:  # noqa: BLE001  live module absent: degrade to empty overlay
        return []
    question_id = synthesis_input.get("question_id") or None
    proposition = synthesis_input.get("proposition") or None
    denominations = synthesis_input.get("denominations") or None
    return retrieve_cultural_chunks(
        doctrine=proposition,
        traditions=denominations,
        question_id=question_id,
        k=8,
    )


# --------------------------------------------------------------------------- #
# Faithful local synthesizer: stands in for the Opus subagent dispatch         #
# --------------------------------------------------------------------------- #

# Word caps mirror bd_mcp.tools.cultural_overlay so the local formatter redacts
# non-redistributable cultural snippets exactly as the cultural handler would.
_SNIPPET_WORD_CAP = 100
_PARAPHRASE_WORD_CAP = 30


def _redact_snippet(text: str, source_work_word_count: int, redistribute: bool) -> str | None:
    """Mirror cultural_overlay._redact_snippet so the overlay respects caps."""
    if redistribute:
        return text
    words = text.split()
    if not words:
        return None
    one_percent_cap = max(1, source_work_word_count // 100) if source_work_word_count > 0 else 0
    effective_cap = (
        min(_SNIPPET_WORD_CAP, one_percent_cap) if one_percent_cap > 0 else _SNIPPET_WORD_CAP
    )
    if effective_cap <= 0:
        return None
    return " ".join(words[:effective_cap])


def _paraphrase(text: str) -> str | None:
    words = text.split()
    if not words:
        return None
    return " ".join(words[:_PARAPHRASE_WORD_CAP]) + (
        " ..." if len(words) > _PARAPHRASE_WORD_CAP else ""
    )


def _format_cultural_overlay(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Group retrieved cultural chunks by tradition, redacting per license.

    The handler downstream redacts independently for its own output, but the
    synthesis subagent's cultural_overlay block must already respect the caps
    (the prose it produces is shaped from these snippets), so we redact here too.
    Immutable: builds fresh dicts, never mutates the input chunks.
    """
    by_tradition: dict[str, list[dict[str, Any]]] = {}
    for ch in chunks:
        tradition = ch.get("tradition") or "unknown"
        redistribute = bool(ch.get("redistribute", False))
        text = ch.get("text", "") or ""
        source_word_count = int(ch.get("source_work_word_count", 0) or 0)
        entry = {
            "work": ch.get("source"),
            "stance": ch.get("stance"),
            "snippet": _redact_snippet(text, source_word_count, redistribute),
            "tradition_paraphrase_if_not_redistributable": (
                None if redistribute else _paraphrase(text)
            ),
            "license": ch.get("license"),
            "redistribute": redistribute,
        }
        by_tradition.setdefault(tradition, []).append(entry)
    return {
        "summary": (
            f"Cultural overlay retrieved {len(chunks)} passage(s) across "
            f"{len(by_tradition)} tradition(s)."
        ),
        "by_tradition": by_tradition,
    }


def _cultural_license_sources(chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Distinct (source, license) pairs from the retrieved cultural chunks."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for ch in chunks:
        source = str(ch.get("source", "<unknown>"))
        license_ = str(ch.get("license", "<unknown>"))
        key = (source, license_)
        if key not in seen:
            seen.add(key)
            out.append({"source": source, "license": license_})
    return out


def _faithful_dispatch(prompt_text: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """A faithful, offline stand-in for the Opus synthesis subagent.

    Reads the locked evidence from the dispatcher-built inputs, echoes the
    verdict axes VERBATIM (never re-derives), formats the retrieved cultural
    chunks into a cultural_overlay block (redaction-aware), folds the lexical
    license stack so the envelope guard can compute share-safety, and writes the
    canonical tmp/pipeline3_synthesis/<task_id>/response.json. Returns the same
    payload so the dispatcher does not need the disk round-trip, but the file is
    written to prove the documented contract.
    """
    evidence_files = inputs["retrieved_lexical"]["evidence_files"]
    ef = evidence_files[0]
    qid = ef["question_id"]
    evidence = ef["evidence"]
    verdict = evidence["verdict"]

    cultural_chunks = inputs["retrieved_cultural"]["chunks"]

    # Lexical license stack: carried verbatim from the locked evidence file so
    # the envelope guard sees the real (possibly non-redistributable) sources.
    lexical_license = evidence.get("license_audit", {}) or {}
    lexical_sources = [
        {"source": s.get("source", "<unknown>"), "license": s.get("license", "<unknown>")}
        for s in lexical_license.get("sources_used", [])
    ]
    sources_used = lexical_sources + _cultural_license_sources(cultural_chunks)

    payload = {
        "task_id": inputs["task_id"],
        "phase": "pipeline3_synthesis",
        "mcp_tool_name": "doctrinal_verdict",
        "user_query": inputs.get("user_query", ""),
        "lexical_verdict": {
            "summary": (
                "Synthesized from the locked evidence file; verdict axes echoed "
                "verbatim, not re-derived."
            ),
            # Verdict axes echoed VERBATIM from the locked evidence.
            "affirms": verdict["affirms"],
            "lexical_breadth": verdict["lexical_breadth"],
            "lexical_directness": verdict["lexical_directness"],
            "variant_stability": verdict["variant_stability"],
            "key_lemmas": [],
            "key_verses": [],
            "source_evidence_files": [f"evidence/{qid}.json"],
        },
        "cultural_overlay": _format_cultural_overlay(cultural_chunks),
        "variant_sensitivity": evidence.get("variants", {}) or {},
        "license_audit": {"sources_used": sources_used},
        "confidence": 1.0,
        "warnings": [],
    }

    # Write the canonical response.json, mirroring the documented subagent contract.
    out_dir = SYNTHESIS_OUTPUT_ROOT / inputs["task_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "response.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


# --------------------------------------------------------------------------- #
# Per-question run + invariant checks                                          #
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


def run_case(case: dict[str, Any], synthesis_fn: Any) -> list[str]:
    """Run one doctrinal_verdict query and check invariants. Returns failures."""
    failures: list[str] = []
    label = case["label"]
    print(f"\n{'=' * 72}")
    print(f"CASE: {label}")
    print(f"  proposition: {case['proposition'][:80]}...")

    env = verdict_handle(
        DoctrinalVerdictInput(
            proposition=case["proposition"],
            denominations=case["denominations"],
            depth="deep",
        ),
        synthesis_fn=synthesis_fn,
        evidence_dir=EVIDENCE_DIR,
        historical_dir=HISTORICAL_DIR,
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

    # 3. Cultural overlay block present (may be empty if store unavailable).
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
    print(f"  synthesis out:  {SYNTHESIS_OUTPUT_ROOT}")

    if not EVIDENCE_DIR.is_dir():
        print(f"FATAL: evidence dir not found: {EVIDENCE_DIR}")
        return 2
    if not HISTORICAL_DIR.is_dir():
        print(f"FATAL: historical dir not found: {HISTORICAL_DIR}")
        return 2

    # Build the synthesis_fn: live cultural retriever + faithful local synthesizer.
    synthesis_fn = make_synthesis_fn(
        dispatch_fn=_faithful_dispatch,
        cultural_retriever=_live_cultural_retriever,
    )

    all_failures: list[str] = []
    all_failures.extend(run_case(WITH_ATTESTATION, synthesis_fn))
    all_failures.extend(run_case(WITHOUT_ATTESTATION, synthesis_fn))

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
