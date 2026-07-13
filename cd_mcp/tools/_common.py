"""Shared helpers for MCP tool modules.

Every tool produces a Common Envelope from retrieval.envelope. Inputs validate
via Pydantic v2 models. Tools may raise ValueError on invalid inputs; the
register layer converts those to an error-envelope response.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from retrieval.envelope import CallerContext, build_envelope

QUESTION_ID_REGEX = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ToolInputBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caller_context: CallerContext = "personal"


def validate_question_id(value: str) -> str:
    if not isinstance(value, str) or not QUESTION_ID_REGEX.match(value):
        raise ValueError(f"invalid question_id {value!r}: must match ^[a-z][a-z0-9-]{{2,80}}$")
    return value


def validate_uuid(value: str) -> str:
    if not isinstance(value, str) or not UUID_REGEX.match(value):
        raise ValueError(f"invalid uuid {value!r}")
    return value


def error_envelope(
    tool: str,
    code: str,
    message: str,
    caller_context: CallerContext = "personal",
) -> dict[str, Any]:
    env = build_envelope(
        tool=tool,
        result=None,
        sources_used=[],
        caller_context=caller_context,
        ok=False,
        error={"code": code, "message": message},
    )
    return env.model_dump(mode="json")


def success_envelope(
    tool: str,
    result: dict[str, Any],
    sources_used: list[dict[str, Any]],
    caller_context: CallerContext = "personal",
    warnings: list[str] | None = None,
    snippet_word_count: int = 0,
    source_work_word_count: int = 0,
) -> dict[str, Any]:
    env = build_envelope(
        tool=tool,
        result=result,
        sources_used=sources_used,
        caller_context=caller_context,
        warnings=warnings,
        snippet_word_count=snippet_word_count,
        source_work_word_count=source_work_word_count,
    )
    return env.model_dump(mode="json")


ScriptureContext = Literal["personal", "public-share", "export"]
