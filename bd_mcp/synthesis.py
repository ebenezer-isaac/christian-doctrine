"""Pipeline 3 synthesis dispatcher.

Bridges the orchestrator's Agent dispatch to the query-synthesis subagent, the
exact mirror of ``pipeline2/dispatcher.py``: an injected ``dispatch_fn`` is the
bridge the orchestrator provides at runtime, a deterministic mock in tests. This
module never imports the anthropic SDK and never invokes Agent itself. There is
no programmatic Anthropic API anywhere in this engine.

The subagent runs the canonical prompt at ``docs/phase_prompts/pipeline3_synthesis.md``.
It reads the locked ``evidence/<id>.json`` (authoritative), the retrieved
cultural chunks (diagnostic), and the locked historical sidecar (diagnostic),
then writes ``tmp/pipeline3_synthesis/<task_id>/response.json``. The doctrinal_verdict
handler transforms that output into the MCP envelope and re-asserts verdict
fidelity. The synthesis subagent never re-derives the lexical verdict.

The ``synthesis_fn`` returned by ``make_synthesis_fn`` matches the injection seam
that ``bd_mcp.tools.doctrinal_verdict.handle`` expects:
``synthesis_fn(synthesis_input: dict) -> dict``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

# dispatch_fn(prompt_text, inputs) -> raw subagent payload (parsed response.json).
DispatchFn = Callable[[str, dict[str, Any]], dict[str, Any]]
# cultural_retriever(synthesis_input) -> list of cultural chunks (handler shape).
# Kept dict-in / list-out so the dispatcher does not depend on the live cultural
# injector's exact keyword signature; the server binds the adapter at wiring time.
CulturalRetriever = Callable[[dict[str, Any]], list[dict[str, Any]]]

PROMPT_PATH = Path("docs/phase_prompts/pipeline3_synthesis.md")
OUTPUT_ROOT = Path("tmp/pipeline3_synthesis")


class SynthesisError(RuntimeError):
    """Raised when the synthesis subagent returns a malformed or absent payload."""


class Pipeline3SynthesisDispatcher:
    """Builds subagent inputs, dispatches one synthesis subagent, returns its payload."""

    def __init__(
        self,
        dispatch_fn: DispatchFn,
        prompt_path: Path | None = None,
        cultural_retriever: CulturalRetriever | None = None,
    ) -> None:
        self.dispatch_fn = dispatch_fn
        self.cultural_retriever = cultural_retriever
        self.prompt_path = prompt_path or PROMPT_PATH
        if not self.prompt_path.exists():
            raise FileNotFoundError(f"synthesis prompt not found: {self.prompt_path}")
        self._prompt_text = self.prompt_path.read_text(encoding="utf-8")

    @property
    def prompt_text(self) -> str:
        return self._prompt_text

    def _retrieve_cultural(self, synthesis_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Retrieve cultural chunks for the subagent. Diagnostic and fail-soft.

        Cultural material never adjudicates the verdict, so a retrieval failure
        must not fail the query: it degrades to an empty overlay.
        """
        if self.cultural_retriever is None:
            return []
        try:
            return list(self.cultural_retriever(synthesis_input))
        except Exception:  # noqa: BLE001  cultural overlay is diagnostic, degrade gracefully
            return []

    def _build_inputs(
        self,
        synthesis_input: dict[str, Any],
        task_id: str,
        cultural_chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        qid = synthesis_input["question_id"]
        return {
            "task_id": task_id,
            "phase": "pipeline3_synthesis",
            "mcp_tool_name": "doctrinal_verdict",
            "user_query": synthesis_input.get("proposition", ""),
            "retrieved_lexical": {
                "evidence_files": [{"question_id": qid, "evidence": synthesis_input["evidence"]}],
                "raw_lexical_chunks": [],
            },
            "retrieved_cultural": {"chunks": cultural_chunks},
            # Historical is locked and read-only for the subagent. The handler
            # attaches the authoritative historical_attestation block itself, so
            # the subagent only references this for prose, never authors it.
            "retrieved_historical": synthesis_input.get("historical", {}),
            "license_constraints": {
                "enforce_redistribution": True,
                "caller_context": synthesis_input.get("caller_context", "personal"),
            },
            "output_path": f"{OUTPUT_ROOT.as_posix()}/{task_id}/",
        }

    def synthesize(self, synthesis_input: dict[str, Any]) -> dict[str, Any]:
        task_id = f"p3-{synthesis_input['question_id']}-{uuid.uuid4().hex[:8]}"
        cultural_chunks = self._retrieve_cultural(synthesis_input)
        inputs = self._build_inputs(synthesis_input, task_id, cultural_chunks)
        raw = self.dispatch_fn(self._prompt_text, inputs)
        return self._post_process(raw, task_id)

    def _post_process(self, raw: dict[str, Any], task_id: str) -> dict[str, Any]:
        payload = raw
        # Some orchestrators write response.json to disk and return an empty ack.
        if not payload:
            payload = load_synthesis_payload(task_id)
        if not isinstance(payload, dict):
            raise SynthesisError(f"synthesis payload not a dict: {type(payload).__name__}")
        if "lexical_verdict" not in payload:
            raise SynthesisError("synthesis payload missing lexical_verdict")
        return payload


def load_synthesis_payload(task_id: str) -> dict[str, Any]:
    """Load a subagent payload the orchestrator dropped to disk before returning."""
    path = OUTPUT_ROOT / task_id / "response.json"
    if not path.exists():
        raise SynthesisError(f"synthesis subagent did not write {path}")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def make_synthesis_fn(
    dispatch_fn: DispatchFn,
    prompt_path: Path | None = None,
    cultural_retriever: CulturalRetriever | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Bind a dispatch_fn (and optional cultural retriever) into the synthesis_fn seam.

    The returned callable is what ``doctrinal_verdict.handle(synthesis_fn=...)``
    invokes. Keeping construction here means ``doctrinal_verdict`` stays a pure
    transform with no knowledge of how a subagent is dispatched.
    """
    dispatcher = Pipeline3SynthesisDispatcher(dispatch_fn, prompt_path, cultural_retriever)

    def synthesis_fn(synthesis_input: dict[str, Any]) -> dict[str, Any]:
        return dispatcher.synthesize(synthesis_input)

    return synthesis_fn
