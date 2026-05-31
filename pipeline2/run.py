"""Pipeline 2 CLI.

Standalone tool that the orchestrator invokes after building the lexical store.
In --mock mode it skips real subagent dispatch and uses a deterministic stub
so the CLI is testable end-to-end without the lexical Neo4j or Opus.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from pipeline2.dispatcher import DispatchFn, Pipeline2Dispatcher
from pipeline2.evidence_schema import Evidence
from pipeline2.persistence import (
    EVIDENCE_DIR,
    list_evidence_files,
    load_evidence,
    persist_evidence,
)
from pipeline2.triangle import triangle_test

LEAN_PROMPT = Path("docs/phase_prompts/pipeline2_verdict.md")
QUESTIONS_PATH = Path("questions.json")


def _mock_dispatch(question_id: str) -> DispatchFn:
    """Return a deterministic stub that emits a minimal v3.1 payload."""

    def fn(_prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        qid = inputs.get("question_id", question_id)
        payload = _build_mock_payload(qid, inputs.get("question_statement", ""))
        return payload

    return fn


def _build_mock_payload(question_id: str, statement: str) -> dict[str, Any]:
    lay_summary = (
        "The lexical evidence for this proposition rests on a single anchor lemma in the "
        "Greek New Testament, supported by one canonical cross reference. The text under "
        "consideration uses the term in its standard grammatical sense, and no contested "
        "variant readings affect the verdict. The complicating texts identified in the "
        "concordance walk are addressed within the same lexical field, and the supporting "
        "verses come from one section of the canon. The verdict here is a mock placeholder "
        "produced by the deterministic stub used in the --mock run. It is not a real "
        "lexical verdict on the proposition. The stub exists so the CLI can be exercised "
        "without dispatching an Opus subagent, and so the persistence and validation paths "
        "can be tested end to end on the local machine. Real verdicts arrive through the "
        "orchestrator at production runtime. The mock keeps the structural fields valid so "
        "the schema validator and the post-processor accept the payload. The mock prose is "
        "intentionally bland and does not assert any theological position one way or the "
        "other; readers should treat any mock evidence file as a placeholder rather than "
        "as an actual verdict on the proposition under examination."
    )
    return {
        "$schema_version": "3.1",
        "id": question_id,
        "question_id": question_id,
        "generated_at": "2026-05-16T00:00:00Z",
        "pipeline_version": "v1",
        "model": "mock-stub",
        "verdict": {
            "affirms": None,
            "lexical_breadth": None,
            "lexical_directness": "silent",
            "variant_stability": None,
            "variant_robust": True,
            "pan_canonical": False,
            "rationale": (
                f"Mock placeholder for {question_id!r}. Statement: {statement[:80]!r}. "
                f"No real lexical reasoning was performed."
            ),
        },
        "lexical_evidence": {
            "anchor_lemmas": [
                {
                    "strong": "G3056",
                    "lemma": "logos",
                    "transliteration": "logos",
                    "occurrences_in_canon": 330,
                    "in_anchors": True,
                }
            ],
            "concordance_traversed": ["G3056"],
            "scripture": [
                {
                    "ref": "John.1.1",
                    "key_terms": [{"strong": "G3056", "lemma": "logos"}],
                    "force": "Mock anchor verse for placeholder evidence.",
                    "supports": "neutral",
                    "genre": "gospel",
                    "figures": [],
                }
            ],
            "cross_refs_invoked": [],
            "complicating_texts": [],
        },
        "variants": {
            "verdict_variant_sensitive": False,
            "variant_units_examined": [],
            "ecm_status": "n/a",
            "note": None,
        },
        "hermeneutics": {
            "primary_method": "grammatico-historical",
            "frameworks_in_play": [],
            "analogia_scripturae": False,
            "progressive_revelation": False,
            "competing_lens_verdicts": [],
            "notes": "Mock stub. No real hermeneutical analysis.",
        },
        "stem_audit": {
            "verdict_preloaded": False,
            "neutralized_form": None,
            "notes": "Mock stub. Stem audit not performed.",
        },
        "lay_summary": lay_summary,
        "citations": [
            {
                "type": "morphology",
                "source": "MorphGNT-morphology",
                "license": "CC-BY-SA-4.0",
                "redistribute": True,
                "ref": "John.1.1",
            }
        ],
        "license_audit": {
            "sources_used": [
                {"source": "MorphGNT-morphology", "license": "CC-BY-SA-4.0", "redistribute": True}
            ],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": ["concordance-thin"],
    }


def _load_question_ids() -> list[str]:
    raw = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    return [q["id"] for q in raw["questions"]]


def _validate_existing() -> int:
    failures: list[tuple[str, str]] = []
    for filename in list_evidence_files():
        qid = filename.removesuffix(".json")
        try:
            load_evidence(qid)
        except Exception as exc:
            failures.append((qid, str(exc)))
    if failures:
        for qid, msg in failures:
            print(f"FAIL {qid}: {msg}", file=sys.stderr)
        return 1
    return 0


def _run_one(
    question_id: str, dispatch_fn: DispatchFn, dispatcher: Pipeline2Dispatcher
) -> Evidence:
    evidence = dispatcher.dispatch_one(question_id, dispatch_fn)
    persist_evidence(evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--question-id",
        help="Single question id, or 'all' to run every question in questions.json",
    )
    parser.add_argument(
        "--triangle",
        action="store_true",
        help="Run the question twice and compare via triangle test",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use a deterministic stub instead of dispatching an Opus subagent",
    )
    parser.add_argument(
        "--validate-existing",
        action="store_true",
        help="Re-validate every evidence/*.json against v3.1 and exit",
    )
    args = parser.parse_args(argv)

    if args.validate_existing:
        return _validate_existing()

    if not args.question_id:
        parser.error("--question-id is required unless --validate-existing is passed")

    if not args.mock:
        print(
            "non-mock dispatch is performed by the orchestrator at runtime; "
            "use --mock to exercise the CLI standalone",
            file=sys.stderr,
        )
        return 2

    from ingest.lexical._common import Settings

    settings: Settings | None
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception:
        settings = None

    dispatcher = Pipeline2Dispatcher.__new__(Pipeline2Dispatcher)
    dispatcher.settings = settings  # type: ignore[assignment]
    dispatcher.lean_prompt_path = LEAN_PROMPT
    dispatcher._prompt_text = LEAN_PROMPT.read_text(encoding="utf-8")

    qids = _load_question_ids() if args.question_id == "all" else [args.question_id]

    dispatch_fn = _mock_dispatch(qids[0])

    if args.triangle:
        if len(qids) != 1:
            parser.error("--triangle works on a single --question-id only")
        with _patched_context_builder(qids[0]):
            result = triangle_test(qids[0], dispatcher, dispatch_fn)
        print(json.dumps({"passed": result.passed, "reasons": list(result.reasons)}, indent=2))
        return 0 if result.passed else 1

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for qid in qids:
        with _patched_context_builder(qid):
            evidence = _run_one(qid, dispatch_fn, dispatcher)
            print(
                f"{qid}: affirms={evidence.verdict.affirms} "
                f"breadth={evidence.verdict.lexical_breadth} "
                f"directness={evidence.verdict.lexical_directness} "
                f"variant={evidence.verdict.variant_stability}"
            )
    return 0


def _patched_context_builder(qid: str) -> AbstractContextManager[None]:
    """Context manager that patches the bundle builder for mock runs.

    Mock dispatch does not need a real bundle; the stub ignores inputs. So we
    replace the bundle builder with a no-op to avoid touching Neo4j.
    """
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def cm() -> Iterator[None]:
        with patch(
            "pipeline2.dispatcher.build_lexical_context_bundle",
            return_value={
                "question_id": qid,
                "question_statement": "",
                "question_metadata": {},
                "lexical_context_bundle": {
                    "anchor_lemmas": [],
                    "anchor_verses": [],
                    "cross_refs": [],
                    "semantic_domain_neighbors": [],
                    "variant_units": [],
                    "syntactic_context": [],
                },
                "schema_version": "3.1",
            },
        ):
            yield

    return cm()


if __name__ == "__main__":
    raise SystemExit(main())
