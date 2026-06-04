"""Pipeline 4 CLI.

Standalone tool the orchestrator invokes after building the historical store.
In --mock mode it skips real subagent dispatch and uses a deterministic stub, so
the CLI is testable end-to-end without the cultural/historical Docker stack
(Neo4j + Qdrant) or Opus.

The mock stub emits attestation_present=false with empty witnesses and an empty
summary, which is the correct common case: most of the 231 questions have no
extra-biblical historical attestation in v1.

Resumable from the filesystem: a question whose historical/<id>.json already
exists is skipped unless re-dispatched (a question id passed explicitly is
always re-dispatched). Mirrors pipeline2/run.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from pipeline4.dispatcher import DispatchFn, Pipeline4Dispatcher
from pipeline4.historical_schema import HistoricalAttestation
from pipeline4.persistence import (
    HISTORICAL_DIR,
    historical_path,
    list_historical_files,
    load_historical,
    persist_historical,
)
from pipeline4.triangle import triangle_test

ATTESTATION_PROMPT = Path("docs/phase_prompts/pipeline4_attestation.md")
QUESTIONS_PATH = Path("questions.json")


def _mock_dispatch(question_id: str) -> DispatchFn:
    """Return a deterministic stub that emits a zero-candidate v1.0 payload."""

    def fn(_prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        qid = inputs.get("question_id", question_id)
        return _build_mock_payload(qid)

    return fn


def _build_mock_payload(question_id: str) -> dict[str, Any]:
    """Minimal attestation_present=false payload (the common zero-candidate case)."""
    return {
        "$schema_version": "1.0",
        "id": question_id,
        "question_id": question_id,
        "generated_at": "2026-06-04T00:00:00Z",
        "pipeline_version": "v1",
        "model": "mock-stub",
        "attestation_present": False,
        "witnesses": [],
        "summary": "No material extra-biblical witness in v1 sources.",
        "license_audit": {
            "sources_used": [],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": [],
    }


def _load_question_ids() -> list[str]:
    raw = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    return [q["id"] for q in raw["questions"]]


def _validate_existing() -> int:
    failures: list[tuple[str, str]] = []
    for filename in list_historical_files():
        qid = filename.removesuffix(".json")
        try:
            load_historical(qid)
        except Exception as exc:
            failures.append((qid, str(exc)))
    if failures:
        for qid, msg in failures:
            print(f"FAIL {qid}: {msg}", file=sys.stderr)
        return 1
    return 0


def _run_one(
    question_id: str,
    dispatch_fn: DispatchFn,
    dispatcher: Pipeline4Dispatcher,
) -> HistoricalAttestation:
    attestation = dispatcher.dispatch_one(question_id, dispatch_fn)
    persist_historical(attestation)
    return attestation


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
        help="Re-validate every historical/*.json against v1.0 and exit",
    )
    args = parser.parse_args(argv)

    if args.validate_existing:
        return _validate_existing()

    if not args.question_id:
        parser.error(
            "--question-id is required unless --validate-existing is passed"
        )

    if not args.mock:
        print(
            "non-mock dispatch is performed by the orchestrator at runtime; "
            "use --mock to exercise the CLI standalone",
            file=sys.stderr,
        )
        return 2

    settings: Any | None
    try:
        from ingest.historical._common import HistoricalSettings

        settings = HistoricalSettings()  # type: ignore[call-arg]
    except Exception:
        settings = None

    dispatcher = Pipeline4Dispatcher.__new__(Pipeline4Dispatcher)
    dispatcher.settings = settings
    dispatcher.prompt_path = ATTESTATION_PROMPT
    dispatcher._prompt_text = ATTESTATION_PROMPT.read_text(encoding="utf-8")

    explicit_single = args.question_id != "all"
    qids = _load_question_ids() if args.question_id == "all" else [args.question_id]

    dispatch_fn = _mock_dispatch(qids[0])

    if args.triangle:
        if len(qids) != 1:
            parser.error("--triangle works on a single --question-id only")
        with _patched_context_builder(qids[0]):
            result = triangle_test(qids[0], dispatcher, dispatch_fn)
        print(
            json.dumps(
                {"passed": result.passed, "reasons": list(result.reasons)}, indent=2
            )
        )
        return 0 if result.passed else 1

    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)
    for qid in qids:
        # Resumable: skip a question already on disk unless it was named
        # explicitly (an explicit single id is always re-dispatched).
        if not explicit_single and historical_path(qid).exists():
            print(f"{qid}: skip (exists)")
            continue
        with _patched_context_builder(qid):
            attestation = _run_one(qid, dispatch_fn, dispatcher)
            print(
                f"{qid}: attestation_present={attestation.attestation_present} "
                f"witnesses={len(attestation.witnesses)} "
                f"safe={attestation.license_audit.evidence_safe_to_publish}"
            )
    return 0


def _patched_context_builder(qid: str) -> AbstractContextManager[None]:
    """Patch the bundle builder for mock runs so no live Neo4j/Qdrant is touched.

    Mock dispatch ignores the bundle, so we replace the builder with a
    zero-candidate stub. This keeps --mock runnable without Docker.
    """
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def cm() -> Iterator[None]:
        with patch(
            "pipeline4.dispatcher.build_historical_context_bundle",
            return_value={
                "phase": "pipeline4_attestation",
                "question_id": qid,
                "question_statement": "",
                "question_metadata": {},
                "lexical_verdict_context": {
                    "schema_ref": "docs/EVIDENCE_SCHEMA.md",
                    "verdict_summary": {
                        "affirms": None,
                        "lexical_directness": None,
                        "rationale": "",
                    },
                    "scripture_anchors": [],
                    "read_only": True,
                },
                "historical_context_bundle": {"candidate_chunks": []},
                "schema_version": "1.0",
            },
        ):
            yield

    return cm()


if __name__ == "__main__":
    raise SystemExit(main())
