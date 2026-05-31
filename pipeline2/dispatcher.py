"""Pipeline 2 dispatcher: bridges orchestrator Agent dispatch to verdict subagents.

The orchestrator owns the actual Agent tool. dispatch_fn is the bridge it
provides at runtime. In tests dispatch_fn is a deterministic mock. The
dispatcher itself never imports the anthropic SDK and never invokes Agent.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ingest.lexical._common import Settings
from pipeline2.context_builder import build_lexical_context_bundle
from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability

DispatchFn = Callable[[str, dict[str, Any]], dict[str, Any]]

WAVE_SIZE = 5


class DispatchError(RuntimeError):
    """Raised when a subagent returned a malformed payload or schema-invalid evidence."""


class Pipeline2Dispatcher:
    """Builds context, dispatches one subagent per question, validates result."""

    def __init__(self, settings: Settings, lean_prompt_path: Path) -> None:
        self.settings = settings
        self.lean_prompt_path = lean_prompt_path
        if not lean_prompt_path.exists():
            raise FileNotFoundError(f"lean prompt not found: {lean_prompt_path}")
        self._prompt_text = lean_prompt_path.read_text(encoding="utf-8")

    @property
    def prompt_text(self) -> str:
        return self._prompt_text

    def _build_inputs(self, question_id: str, task_id: str) -> dict[str, Any]:
        bundle = build_lexical_context_bundle(question_id, self.settings)
        return {
            "task_id": task_id,
            "phase": "pipeline2_verdict",
            **bundle,
            "output_path": f"tmp/pipeline2_verdict/{task_id}/",
        }

    def _post_process(self, raw: dict[str, Any]) -> Evidence:
        if not isinstance(raw, dict):
            raise DispatchError(f"subagent payload not a dict: {type(raw).__name__}")
        evidence = Evidence.model_validate(raw)
        breadth = compute_lexical_breadth(evidence)
        stability = compute_variant_stability(evidence)
        evidence_dict = evidence.model_dump(by_alias=True)
        evidence_dict["verdict"]["lexical_breadth"] = breadth
        evidence_dict["verdict"]["variant_stability"] = stability
        return Evidence.model_validate(evidence_dict)

    def dispatch_one(
        self,
        question_id: str,
        dispatch_fn: DispatchFn,
    ) -> Evidence:
        task_id = f"p2-{question_id}-{uuid.uuid4().hex[:8]}"
        inputs = self._build_inputs(question_id, task_id)
        result = dispatch_fn(self._prompt_text, inputs)
        return self._post_process(result)

    def dispatch_all(
        self,
        dispatch_fn: DispatchFn,
        question_ids: list[str],
        wave_size: int = WAVE_SIZE,
    ) -> list[Evidence]:
        out: list[Evidence] = []
        for i in range(0, len(question_ids), wave_size):
            wave = question_ids[i : i + wave_size]
            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                futures = [pool.submit(self.dispatch_one, qid, dispatch_fn) for qid in wave]
                for fut in futures:
                    out.append(fut.result())
        return out


def load_subagent_payload(task_id: str) -> dict[str, Any]:
    """Helper for orchestrators that drop subagent JSON to disk before dispatch returns."""
    path = Path(f"tmp/pipeline2_verdict/{task_id}/evidence.json")
    if not path.exists():
        raise DispatchError(f"subagent did not write {path}")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
