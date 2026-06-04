"""Pipeline 4 dispatcher: bridges orchestrator Agent dispatch to attestation subagents.

Mirrors pipeline2/dispatcher.py. The orchestrator owns the actual Agent tool;
dispatch_fn is the bridge it provides at runtime. In tests dispatch_fn is a
deterministic mock. The dispatcher itself never imports the anthropic SDK and
never invokes Agent.

The post-processor validates the raw subagent dict against the v1.0
HistoricalAttestation model and recomputes license_audit.evidence_safe_to_publish
from the witness license stack via the model method, so a subagent cannot
mislabel a non-redistributable witness as publish-safe.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pipeline4.context_builder import build_historical_context_bundle
from pipeline4.historical_schema import HistoricalAttestation

DispatchFn = Callable[[str, dict[str, Any]], dict[str, Any]]

DEFAULT_PROMPT_PATH = Path("docs/phase_prompts/pipeline4_attestation.md")
WAVE_SIZE = 5


class DispatchError(RuntimeError):
    """Raised when a subagent returned a malformed payload or schema-invalid attestation."""


class Pipeline4Dispatcher:
    """Builds context, dispatches one subagent per question, validates result."""

    def __init__(
        self, settings: Any, prompt_path: Path = DEFAULT_PROMPT_PATH
    ) -> None:
        self.settings = settings
        self.prompt_path = prompt_path
        if not prompt_path.exists():
            raise FileNotFoundError(f"attestation prompt not found: {prompt_path}")
        self._prompt_text = prompt_path.read_text(encoding="utf-8")

    @property
    def prompt_text(self) -> str:
        return self._prompt_text

    def _build_inputs(self, question_id: str, task_id: str) -> dict[str, Any]:
        bundle = build_historical_context_bundle(question_id, self.settings)
        return {
            "task_id": task_id,
            **bundle,
            "output_path": f"tmp/pipeline4_attestation/{task_id}/",
            "schema_version": "1.0",
        }

    def _post_process(self, raw: dict[str, Any]) -> HistoricalAttestation:
        if not isinstance(raw, dict):
            raise DispatchError(
                f"subagent payload not a dict: {type(raw).__name__}"
            )
        attestation = HistoricalAttestation.model_validate(raw)
        # Recompute evidence_safe_to_publish from the witness license stack
        # (schema formula). A subagent cannot mislabel a non-redistributable
        # witness as publish-safe.
        recomputed = attestation.recompute_evidence_safe_to_publish()
        if recomputed == attestation.license_audit.evidence_safe_to_publish:
            return attestation
        data = attestation.model_dump(by_alias=True, mode="json")
        data["license_audit"]["evidence_safe_to_publish"] = recomputed
        if recomputed:
            data["license_audit"]["non_redistributable_reason"] = None
        elif not data["license_audit"].get("non_redistributable_reason"):
            unsafe = sorted(
                {
                    s.source_slug
                    for s in attestation.license_audit.sources_used
                    if not s.redistribute
                }
            )
            data["license_audit"]["non_redistributable_reason"] = (
                "Cites a non-redistributable source: " + ", ".join(unsafe) + "."
                if unsafe
                else "Cites a non-redistributable source."
            )
        return HistoricalAttestation.model_validate(data)

    def dispatch_one(
        self,
        question_id: str,
        dispatch_fn: DispatchFn,
    ) -> HistoricalAttestation:
        task_id = f"p4-{question_id}-{uuid.uuid4().hex[:8]}"
        inputs = self._build_inputs(question_id, task_id)
        result = dispatch_fn(self._prompt_text, inputs)
        return self._post_process(result)

    def dispatch_all(
        self,
        dispatch_fn: DispatchFn,
        question_ids: list[str],
        wave_size: int = WAVE_SIZE,
    ) -> list[HistoricalAttestation]:
        out: list[HistoricalAttestation] = []
        for i in range(0, len(question_ids), wave_size):
            wave = question_ids[i : i + wave_size]
            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                futures = [
                    pool.submit(self.dispatch_one, qid, dispatch_fn) for qid in wave
                ]
                for fut in futures:
                    out.append(fut.result())
        return out


def load_subagent_payload(task_id: str) -> dict[str, Any]:
    """Helper for orchestrators that drop subagent JSON to disk before dispatch returns."""
    path = Path(f"tmp/pipeline4_attestation/{task_id}/historical.json")
    if not path.exists():
        raise DispatchError(f"subagent did not write {path}")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
